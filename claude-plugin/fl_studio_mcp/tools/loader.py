"""Plugin loading through FL Studio's own Browser.

FL's scripting API has no "load plugin" function (channels/mixer/general
expose no add/load/create call). FL's Browser, however, can: its "Plugin
database" tree mirrors the .fst shortcuts FL writes for every scanned plugin,
and confirming a node there loads that plugin (effects -> the selected mixer
track, generators -> the Channel Rack).

So: the server finds the plugin's .fst on disk (music/plugin_library.py),
turns it into a Browser path, the controller script walks that path with the
public ui.navigateBrowser / ui.toggleBrowserNode API (no mouse or keyboard
simulation) and confirms it. FL finishes the load after the script callback
returns, so this tool then VERIFIES by re-reading the mixer slots / channel
count and only reports success when the plugin actually appeared.
"""
from __future__ import annotations

import time
from typing import Annotated, List, Optional

from fastmcp import FastMCP
from pydantic import Field

from .. import protocol, safety
from ..connection import get_bridge
from ..music import plugin_library as pl

_FIND_TIMEOUT = 25.0     # the Browser walk can take a few hundred steps
_VERIFY_SECONDS = 4.0


def describe_load_limitation(name: str, as_generator: bool) -> dict:
    """Fallback explanation when the Browser route is unavailable. PURE."""
    where = ("channel rack (a generator/instrument)" if as_generator
             else "a mixer insert slot (an effect)")
    return {
        "ok": False,
        "supported": False,
        "requested": {"name": name, "as_generator": as_generator},
        "reason": ("Loading goes through FL's Browser (Plugin database); it needs FL "
                   "scripting API 34+ (ui.toggleBrowserNode) and the plugin scanned "
                   "into FL's plugin database."),
        "recommended": [
            "Load '%s' manually into %s, or rescan plugins in FL "
            "(Options > Manage plugins > Find plugins) and try again." % (name, where),
        ],
    }


def _effect_slots(bridge, track):
    res = bridge.call(protocol.CMD_PLUGIN_LIST, {"track": track}) or {}
    return {s["slot"]: s.get("name", "") for s in res.get("slots", [])}


def _channel_count(bridge):
    return int((bridge.call(protocol.CMD_SESSION_INFO) or {}).get("channels", 0))


def _wait_for(check, sleep):
    deadline = time.time() + _VERIFY_SECONDS
    while True:
        res = check()
        if res is not None or time.time() >= deadline:
            return res
        sleep(0.25)


def _collapse(bridge, path, skips):
    """Fold the Browser back so the next load starts from a short list."""
    try:
        bridge.call(protocol.CMD_BROWSER_COLLAPSE, {"path": path, "skips": skips})
    except Exception:
        pass


def load_plugin(bridge, name, kind="auto", track=None, sleep=time.sleep):
    """Resolve, aim, walk the Browser, confirm, verify, restore.

    Verified on FL 26.1 (API 45): confirming a Browser effect puts it in the
    next free slot of the mixer track the SELECTED CHANNEL feeds, so we point
    that channel at `track` first and restore it after. A confirmed generator
    replaces the selected channel's plugin, so we deselect all channels first
    (and restore the selection after)."""
    found = pl.resolve_plugin(name, kind)
    if not found.get("found"):
        return {"ok": False, "error": found.get("error") or "No installed plugin matches '%s'." % name,
                "hint": "Use fl_list_installed_plugins to see exact names."}
    matches = found["matches"]
    if not found["exact"] and len({m["name"] for m in matches}) > 1:
        return {"ok": False, "error": "Several plugins match '%s'; pick one." % name,
                "candidates": sorted({m["name"] for m in matches})}
    target = matches[0]
    skips = pl.browser_skips(target["path"])
    find = {"path": target["path"], "skips": skips, "confirm": True}

    if target["kind"] == "effect":
        if track is None:
            return {"ok": False, "error": "Effects need a mixer track (track=...)."}
        before = _effect_slots(bridge, track)
        if len(before) >= 10:
            return {"ok": False, "error": "Mixer track %d has no free effect slot." % track}
        aim = bridge.call(protocol.CMD_FX_TARGET, {"op": "set", "track": track}) or {}
        try:
            walk = bridge.call(protocol.CMD_BROWSER_FIND, find, timeout=_FIND_TIMEOUT) or {}
            if not walk.get("found"):
                return {"ok": False, "error": "Could not reach the plugin in FL's Browser.",
                        "plugin": target["name"], "browser": walk}

            def check():
                after = _effect_slots(bridge, track)
                new = {s: n for s, n in after.items() if s not in before}
                return sorted(new.items())[0] if new else None
            hit = _wait_for(check, sleep)
        finally:
            if "channel" in aim:
                bridge.call(protocol.CMD_FX_TARGET, {"op": "restore", "channel": aim["channel"],
                                                      "previous": aim["previous"]})
        if hit:
            _collapse(bridge, target["path"], skips)
            return {"ok": True, "loaded": hit[1], "kind": "effect", "track": track,
                    "slot": hit[0], "format": target["format"]}
        return {"ok": False, "error": "FL reached the plugin but it did not appear on track %d." % track,
                "plugin": target["name"], "browser": walk}

    # generator
    sel = bridge.call(protocol.CMD_CHANNEL_SELECTION, {"op": "save"}) or {}
    before = int(sel.get("count", _channel_count(bridge)))
    bridge.call(protocol.CMD_CHANNEL_SELECTION, {"op": "clear"})
    hit = None
    try:
        walk = bridge.call(protocol.CMD_BROWSER_FIND, find, timeout=_FIND_TIMEOUT) or {}
        if not walk.get("found"):
            return {"ok": False, "error": "Could not reach the plugin in FL's Browser.",
                    "plugin": target["name"], "browser": walk}
        hit = _wait_for(lambda: (_channel_count(bridge) if _channel_count(bridge) > before else None), sleep)
    finally:
        # A new channel stays selected (like loading by hand); otherwise put the
        # old selection back.
        if not hit:
            bridge.call(protocol.CMD_CHANNEL_SELECTION, {"op": "restore", "selected": sel.get("selected", [])})
    if hit:
        return {"ok": True, "loaded": target["name"], "kind": "generator", "channel": hit - 1,
                "format": target["format"]}
    return {"ok": False, "error": "FL reached the instrument but no new channel appeared.",
            "plugin": target["name"], "browser": walk,
            "hint": "If an existing channel changed instead, undo it in FL (Cmd/Ctrl+Z)."}


def register(mcp: FastMCP) -> None:
    @mcp.tool(annotations={
        "title": "Load a plugin (via FL's Browser)",
        "readOnlyHint": False, "destructiveHint": False, "openWorldHint": True,
    })
    def fl_load_plugin(
        name: Annotated[str, Field(description="Installed plugin name as FL lists it, e.g. 'Pro-Q 3'.")],
        track: Annotated[Optional[int], Field(ge=0, description="Mixer track for an effect (0 = Master). Not used for instruments.")] = None,
        kind: Annotated[str, Field(description="'effect', 'generator' or 'auto' (decide from FL's plugin database).")] = "auto",
    ) -> dict:
        """Load an installed plugin into FL Studio: effects go into the first
        free slot of `track`, instruments become a new Channel Rack channel.

        Walks FL's own Browser (Plugin database) with the official scripting
        API, then VERIFIES the plugin appeared before reporting ok. Use
        fl_list_installed_plugins for exact names. Undo with Ctrl/Cmd+Z in FL."""
        plan = safety.preview_write(tool="load_plugin",
                                    params={"name": name, "track": track, "kind": kind})
        if plan:
            return plan
        return load_plugin(get_bridge(), name, kind, track)

    @mcp.tool(annotations={"title": "Peek at FL's Browser (diagnosis)", "readOnlyHint": True})
    def fl_browser_peek(
        count: Annotated[int, Field(ge=1, le=25, description="How many items to read from the current one.")] = 10,
    ) -> dict:
        """Diagnosis for fl_load_plugin: the focused FL Browser item and the
        next few captions (marks folders). Moves only the Browser selection."""
        return get_bridge().call(protocol.CMD_BROWSER_PEEK, {"count": count})

    @mcp.tool(annotations={"title": "Run UI steps (diagnosis)", "readOnlyHint": False})
    def fl_ui_steps(
        steps: Annotated[List[List], Field(description=(
            "Steps run in order inside FL, e.g. [['select_track',3],['active_fx'],['slots',3]]. "
            "Allowed: select_track t [flags], active_track t, deselect_all, focus_editor t s, "
            "active_fx, track_number, show wid, focus wid, form, focused_plugin, escape, enter, "
            "find <captions...>, chan_target t, chan_target_get, slots t."))],
    ) -> dict:
        """Diagnosis for plugin loading: run whitelisted UI/mixer steps in one
        FL callback and get each result. Not for everyday use."""
        return get_bridge().call(protocol.CMD_UI_STEPS, {"steps": steps}, timeout=_FIND_TIMEOUT)
