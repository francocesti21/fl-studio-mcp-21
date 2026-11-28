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


def load_plugin(bridge, name, kind="auto", track=None, sleep=time.sleep):
    """Resolve, walk the Browser, confirm, then verify. Returns a result dict."""
    found = pl.resolve_plugin(name, kind)
    if not found.get("found"):
        return {"ok": False, "error": found.get("error") or "No installed plugin matches '%s'." % name,
                "hint": "Use fl_list_installed_plugins to see exact names."}
    matches = found["matches"]
    if not found["exact"] and len({m["name"] for m in matches}) > 1:
        return {"ok": False, "error": "Several plugins match '%s'; pick one." % name,
                "candidates": sorted({m["name"] for m in matches})}
    target = matches[0]
    is_fx = target["kind"] == "effect"
    if is_fx and track is None:
        return {"ok": False, "error": "Effects need a mixer track (track=...)."}

    params = {"path": target["path"], "confirm": True}
    if is_fx:
        before = _effect_slots(bridge, track)
        free = [s for s in range(10) if s not in before]
        if not free:
            return {"ok": False, "error": "Mixer track %d has no free effect slot." % track}
        params.update({"track": track, "slot": free[0]})
    else:
        before = _channel_count(bridge)

    walk = bridge.call(protocol.CMD_BROWSER_FIND, params, timeout=_FIND_TIMEOUT) or {}
    if not walk.get("found"):
        return {"ok": False, "error": "Could not reach the plugin in FL's Browser.",
                "plugin": target["name"], "browser": walk}

    # FL loads after the script callback returns: poll until it shows up.
    deadline = time.time() + _VERIFY_SECONDS
    while True:
        if is_fx:
            after = _effect_slots(bridge, track)
            new = {s: n for s, n in after.items() if before.get(s) != n}
            if new:
                slot, loaded = sorted(new.items())[0]
                return {"ok": True, "loaded": loaded, "kind": "effect", "track": track,
                        "slot": slot, "format": target["format"]}
        else:
            after = _channel_count(bridge)
            if after > before:
                return {"ok": True, "loaded": target["name"], "kind": "generator",
                        "channel": after - 1, "format": target["format"]}
        if time.time() >= deadline:
            return {"ok": False, "error": "FL reached the plugin but nothing new appeared.",
                    "plugin": target["name"], "browser": walk,
                    "hint": "Click the FL window once (so its Browser can take focus) and retry."}
        sleep(0.25)


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
