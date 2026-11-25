"""Session organizer (fl-studio-mcp-21).

Organize a whole FL Studio session in one tool call instead of dozens of
screen clicks: names, colors, volumes and bus routing on the mixer, matching
names and colors on the playlist, and channel-rack names / colors / mixer
targets.

The controller does the writes with one compact command (``apply_ops``); the
judgement -- layouts, rainbow gradients, which track goes to which bus --
lives here. Every target (one mixer track, one playlist track or one channel)
is one write in a single ``safe_write_group``, so ``fl_rollback_last_change``
undoes the whole organization in one step.

FL API limits worth knowing (no script can do these, so the tools report them
instead of failing silently):
  * Mixer tracks cannot be created by a script. The template checks the count
    first and says how many to add (Mixer > Insert multiple).
  * "Assign to new Audio track(s)" (the playlist <-> mixer link) has no API.
    The organizer copies names and colors to the playlist tracks instead.
  * Docking tracks left/right has no setter (only getTrackDockSide).
"""
from __future__ import annotations

import colorsys
import json
from typing import Annotated, Any, Dict, List, Optional, Union

from fastmcp import FastMCP
from pydantic import BaseModel, Field

from .. import protocol, safety
from ..connection import fetch_all_pages, get_bridge
from .color import parse_color

# Op arrays must keep one request under the SysEx budget.
_OP_BUDGET = 480


# -- pure helpers -------------------------------------------------------------

def rainbow(n: int, hue_start: float = 0.0, hue_end: float = 285.0,
            saturation: float = 0.82, value: float = 0.95) -> List[tuple]:
    """n RGB colors spread from hue_start to hue_end (degrees). PURE."""
    if n <= 0:
        return []
    out = []
    for i in range(n):
        h = hue_start + (hue_end - hue_start) * (i / (n - 1) if n > 1 else 0)
        r, g, b = colorsys.hsv_to_rgb((h % 360) / 360.0, saturation, value)
        out.append((round(r * 255), round(g * 255), round(b * 255)))
    return out


def _rgb(spec) -> Optional[tuple]:
    if spec is None:
        return None
    if isinstance(spec, (list, tuple)) and len(spec) == 3:
        return tuple(int(x) for x in spec)
    return parse_color(spec)


def hex_of(rgb) -> Optional[str]:
    return None if rgb is None else "#%02X%02X%02X" % tuple(rgb)


def _chunks_ok(ops) -> bool:
    return len(json.dumps(ops, separators=(",", ":"))) <= _OP_BUDGET


def restore_ops(item) -> List[list]:
    """Ops that put one state_dump item back. PURE."""
    if not item or len(item) < 3 or item[2] is None:
        return []                      # target did not exist: nothing to restore
    kind, i = item[0], item[1]
    if kind == "m":
        _, _, name, color, vol, dsts = item
        ops = [["mn", i, name], ["mC", i, color], ["mv", i, vol], ["mx", i]]
        ops += [["mr", i, d, 1] for d in dsts]
        return ops
    if kind == "p":
        _, _, name, color = item
        return [["pn", i, name], ["pC", i, color]]
    _, _, name, color, tgt = item
    ops = [["cn", i, name], ["cC", i, color]]
    if isinstance(tgt, int) and tgt >= 0:
        ops.append(["ct", i, tgt])
    return ops


def mixer_ops(track: int, name=None, color=None, volume_db=None,
              route_to: Optional[List[int]] = None) -> List[list]:
    """Ops for one mixer track. route_to=None leaves routing alone; a list
    makes the routing EXCLUSIVE (every other send, Master included, is
    removed). PURE."""
    ops = []
    if name is not None:
        ops.append(["mn", track, str(name)[:64]])
    if color is not None:
        ops.append(["mc", track] + list(color))
    if volume_db is not None:
        ops.append(["md", track, float(volume_db)])
    if route_to is not None:
        ops.append(["mx", track])
        ops += [["mr", track, int(d), 1] for d in route_to]
    return ops


# -- layout planner -----------------------------------------------------------

EXAMPLE_GROUPS = [  # example only (tests/docs); the tool has no default layout
    {"name": "Drums", "count": 5, "sum": "INSTRUMENTAL"},
    {"name": "Melodías", "count": 5, "sum": "INSTRUMENTAL"},
    {"name": "Efectos", "count": 5, "sum": "INSTRUMENTAL"},
    {"name": "Voces", "count": 5, "sum": "VOCES"},
    {"name": "Armonías", "count": 5, "sum": "VOCES"},
]


def plan_template(groups, *, start_track=1, buses=True, bus_prefix="BUS ",
                  mixbus="MIXBUS", sum_color=(176, 176, 176),
                  mixbus_color=(255, 255, 255), hue_start=0.0, hue_end=285.0,
                  playlist=True, playlist_start=1) -> Dict[str, Any]:
    """Turn a group spec into a full mixer + playlist layout. PURE.

    groups: [{"name", "count", "color"?, "sum"?}] -- channels are numbered
    "<name> 1..count". Without a color every channel gets its own step of one
    rainbow gradient across ALL channels. "sum" names an intermediate bus
    (e.g. INSTRUMENTAL); buses -> sums -> mixbus -> Master.
    """
    total = sum(int(g["count"]) for g in groups)
    grad = rainbow(total, hue_start, hue_end)
    tracks, t, k = [], int(start_track), 0
    group_rows = []
    for g in groups:
        fixed = _rgb(g.get("color"))
        rows = []
        for n in range(int(g["count"])):
            rows.append({"track": t, "name": "%s %d" % (g["name"], n + 1),
                         "color": fixed or grad[k], "role": "channel",
                         "group": g["name"]})
            t += 1
            k += 1
        group_rows.append((g, rows))
        tracks += rows
    bus_of = {}
    if buses:
        for g, rows in group_rows:
            mid = rows[len(rows) // 2]["color"] if rows else (128, 128, 128)
            bus = {"track": t, "name": bus_prefix + g["name"].upper(),
                   "color": _rgb(g.get("bus_color")) or mid, "role": "bus",
                   "group": g["name"]}
            bus_of[g["name"]] = bus
            tracks.append(bus)
            t += 1
    sums = []
    for g in groups:
        s = g.get("sum")
        if s and s not in sums:
            sums.append(s)
    sum_of = {}
    for s in sums:
        row = {"track": t, "name": s, "color": tuple(sum_color), "role": "sum"}
        sum_of[s] = row
        tracks.append(row)
        t += 1
    mix = None
    if mixbus:
        mix = {"track": t, "name": mixbus, "color": tuple(mixbus_color), "role": "mixbus"}
        tracks.append(mix)
        t += 1
    top = mix["track"] if mix else 0
    # routing
    for g, rows in group_rows:
        s = sum_of.get(g.get("sum"))
        after_bus = s["track"] if s else top
        if buses:
            for r in rows:
                r["route_to"] = [bus_of[g["name"]]["track"]]
            bus_of[g["name"]]["route_to"] = [after_bus]
        else:
            for r in rows:
                r["route_to"] = [after_bus]
    for s in sum_of.values():
        s["route_to"] = [top]
    if mix:
        mix["route_to"] = [0]
    pl = []
    if playlist:
        for n, r in enumerate([r for r in tracks if r["role"] == "channel"]):
            pl.append({"track": playlist_start + n, "name": r["name"], "color": r["color"]})
    return {"mixer": tracks, "playlist": pl, "last_track": t - 1}


# -- executor -----------------------------------------------------------------

def _write_for(kind: str, idx: int, ops: List[list]) -> dict:
    key = {"m": "m", "p": "pl", "c": "ch"}[kind]
    scope = "state:" + json.dumps({key: [idx]}, separators=(",", ":"))

    def restore(before):
        items = (before or {}).get("items") or []
        return {"command": protocol.CMD_APPLY_OPS,
                "params": {"ops": restore_ops(items[0] if items else None)}}
    return {"snap_scope": scope, "command": protocol.CMD_APPLY_OPS,
            "params": {"ops": ops}, "restore": restore}


def build_writes(mixer=(), playlist=(), channels=()) -> List[dict]:
    """safe_write_group entries, one per target. PURE (except closures)."""
    writes = []
    for kind, rows in (("m", mixer), ("p", playlist), ("c", channels)):
        for idx, ops in rows:
            if not ops:
                continue
            if not _chunks_ok(ops):
                raise ValueError("too many ops for target %s%d" % (kind, idx))
            writes.append(_write_for(kind, idx, ops))
    return writes


def _verify(bridge, mixer_rows, playlist_rows):
    """Read everything back and list what did not land."""
    m = [r["track"] for r in mixer_rows]
    p = [r["track"] for r in playlist_rows]
    if not m and not p:
        return []
    items = fetch_all_pages(bridge, protocol.CMD_STATE_DUMP, "items",
                            params={"m": m, "pl": p}).get("items", [])
    got = {(it[0], it[1]): it for it in items}
    bad = []
    for r in mixer_rows:
        it = got.get(("m", r["track"]))
        if not it or it[2] is None:
            bad.append({"mixer": r["track"], "issue": "track does not exist"})
            continue
        if r.get("name") is not None and it[2] != str(r["name"])[:32]:
            bad.append({"mixer": r["track"], "issue": "name", "got": it[2]})
        if r.get("route_to") is not None and sorted(it[5]) != sorted(r["route_to"]):
            bad.append({"mixer": r["track"], "issue": "routing", "got": it[5],
                        "want": r["route_to"]})
    for r in playlist_rows:
        it = got.get(("p", r["track"]))
        if not it or it[2] is None:
            bad.append({"playlist": r["track"], "issue": "track does not exist"})
        elif r.get("name") is not None and it[2] != str(r["name"])[:32]:
            bad.append({"playlist": r["track"], "issue": "name", "got": it[2]})
    return bad


def apply_layout(bridge, *, tool, mixer_rows=(), playlist_rows=(), channel_rows=()):
    writes = build_writes(
        mixer=[(r["track"], mixer_ops(r["track"], r.get("name"), r.get("color"),
                                      r.get("volume_db"), r.get("route_to")))
               for r in mixer_rows],
        playlist=[(r["track"], ([["pn", r["track"], str(r["name"])[:64]]] if r.get("name") is not None else [])
                   + ([["pc", r["track"]] + list(r["color"])] if r.get("color") is not None else []))
                  for r in playlist_rows],
        channels=[(r["channel"], ([["cn", r["channel"], str(r["name"])[:64]]] if r.get("name") is not None else [])
                   + ([["cc", r["channel"]] + list(r["color"])] if r.get("color") is not None else [])
                   + ([["ct", r["channel"], int(r["mixer_track"])]] if r.get("mixer_track") is not None else []))
                  for r in channel_rows],
    )
    if not writes:
        return {"ok": False, "error": "nothing to change"}
    res = safety.safe_write_group(bridge, tool=tool, scope="organizer", writes=writes)
    if res.get("dry_run"):
        return res
    errors = [a.get("errors") for a in res.get("after", []) if isinstance(a, dict) and a.get("errors")]
    mismatches = _verify(bridge, list(mixer_rows), list(playlist_rows))
    return {"ok": not errors and not mismatches, "writes": len(writes),
            "errors": errors, "mismatches": mismatches,
            "undo": "fl_rollback_last_change"}


# -- tool models ----------------------------------------------------------------

class MixerTrackSpec(BaseModel):
    track: int = Field(ge=0, description="Mixer track index (0 = Master).")
    name: Optional[str] = None
    color: Optional[str] = Field(None, description="Color name or hex, e.g. '#F22C2C'.")
    volume_db: Optional[float] = None
    route_to: Optional[List[int]] = Field(
        None, description="EXCLUSIVE routing: the track sends only to these tracks "
                          "(0 = Master). Omit to leave routing as is.")


class PlaylistTrackSpec(BaseModel):
    track: int = Field(ge=1, description="Playlist track (1-based).")
    name: Optional[str] = None
    color: Optional[str] = None


class ChannelSpec(BaseModel):
    channel: int = Field(ge=0, description="Channel Rack index (0-based).")
    name: Optional[str] = None
    color: Optional[str] = None
    mixer_track: Optional[int] = Field(None, ge=0, description="Mixer track this channel feeds.")


class GroupSpec(BaseModel):
    name: str = Field(description="Group name, e.g. 'Drums'. Channels become 'Drums 1..N'.")
    count: int = Field(ge=1, le=60)
    color: Optional[str] = Field(None, description="One color for the whole group; omit for the rainbow gradient.")
    sum: Optional[str] = Field(None, description="Intermediate bus this group's bus feeds, e.g. 'INSTRUMENTAL'.")


def _colorize(rows, key="color"):
    out = []
    for r in rows:
        d = r.model_dump() if hasattr(r, "model_dump") else dict(r)
        if d.get(key) is not None:
            rgb = _rgb(d[key])
            if rgb is None:
                raise ValueError("unknown color %r" % d[key])
            d[key] = rgb
        out.append(d)
    return out


def register(mcp: FastMCP) -> None:
    _RO = {"readOnlyHint": True, "destructiveHint": False,
           "idempotentHint": True, "openWorldHint": True}
    _WR = {"readOnlyHint": False, "destructiveHint": False,
           "idempotentHint": False, "openWorldHint": True}

    @mcp.tool(annotations={"title": "Session counts", **_RO})
    def fl_session_info() -> dict:
        """How many mixer tracks, playlist tracks and channels the open project
        has. Check this before organizing: scripts cannot create mixer tracks."""
        return get_bridge().call(protocol.CMD_SESSION_INFO)

    @mcp.tool(annotations={"title": "Organize session (batch)", **_WR})
    def fl_organize_session(
        mixer: Annotated[Optional[List[MixerTrackSpec]], Field(description="Mixer tracks to name / color / set volume / route.")] = None,
        playlist: Annotated[Optional[List[PlaylistTrackSpec]], Field(description="Playlist tracks to name / color.")] = None,
        channels: Annotated[Optional[List[ChannelSpec]], Field(description="Channel Rack channels to name / color / send to a mixer track.")] = None,
        mirror_playlist: Annotated[bool, Field(description="Also copy the listed mixer names/colors onto playlist tracks 1..N, in the order given (ignored when playlist is given).")] = False,
    ) -> dict:
        """Apply many organizing changes in ONE step: mixer names, colors,
        volumes and exclusive routing; playlist names and colors; channel
        names, colors and mixer targets. Reads everything back to verify and
        is ONE rollback unit (fl_rollback_last_change)."""
        try:
            m = _colorize(mixer or [])
            p = _colorize(playlist or [])
            c = _colorize(channels or [])
        except ValueError as e:
            return {"ok": False, "error": str(e)}
        if mirror_playlist and not p:
            p = [{"track": n + 1, "name": r.get("name"), "color": r.get("color")}
                 for n, r in enumerate(m)]
        return apply_layout(get_bridge(), tool="organize_session",
                            mixer_rows=m, playlist_rows=p, channel_rows=c)

    @mcp.tool(annotations={"title": "Build mixer + playlist template", **_WR})
    def fl_build_template(
        groups: Annotated[List[GroupSpec], Field(description="The user's groups, in order, exactly as they describe them (names, channel counts, colors, which intermediate bus each feeds). Ask the user if anything is unclear; there is no built-in layout.")],
        start_track: Annotated[int, Field(ge=1)] = 1,
        buses: Annotated[bool, Field(description="One bus per group ('BUS DRUMS'...).")] = True,
        mixbus: Annotated[Optional[str], Field(description="Final bus before Master; empty to skip.")] = "MIXBUS",
        playlist: Annotated[bool, Field(description="Name and color playlist tracks 1..N like the channels. Set FALSE if the user will link the tracks with 'Assign to new Audio track(s)': FL treats named playlist tracks as used and puts the linked tracks after them (linked tracks inherit name and color anyway).")] = True,
        hue_start: Annotated[float, Field(description="Rainbow start hue in degrees.")] = 0.0,
        hue_end: Annotated[float, Field(description="Rainbow end hue in degrees.")] = 285.0,
        preview: Annotated[bool, Field(description="Only return the plan, change nothing.")] = False,
    ) -> dict:
        """Build the user's own session template in one call, from their
        description: numbered channels per group (a group color, or a
        rainbow gradient for groups without one), optional bus per group,
        optional intermediate buses (e.g. INSTRUMENTAL), an optional final
        bus to Master, and matching playlist names/colors. Use preview=true
        to show the plan first. Checks first that the project has enough mixer tracks
        (scripts cannot add them). ONE rollback unit."""
        gs = [g.model_dump() for g in groups]
        plan = plan_template(gs, start_track=start_track, buses=buses,
                             mixbus=mixbus or None, playlist=playlist,
                             hue_start=hue_start, hue_end=hue_end)
        summary = [{"track": r["track"], "name": r["name"], "color": hex_of(r["color"]),
                    "to": r.get("route_to")} for r in plan["mixer"]]
        if preview:
            return {"ok": True, "preview": True, "mixer": summary,
                    "playlist_tracks": len(plan["playlist"])}
        b = get_bridge()
        info = b.call(protocol.CMD_SESSION_INFO)
        have = int(info.get("mixer_tracks", 0)) - 1     # minus Master
        need = plan["last_track"]
        if have < need:
            return {"ok": False, "error": "not enough mixer tracks",
                    "have": have, "need": need, "add": need - have,
                    "how": "Mixer menu > Insert multiple (add %d), then run again." % (need - have)}
        res = apply_layout(b, tool="build_template", mixer_rows=plan["mixer"],
                           playlist_rows=plan["playlist"])
        res["mixer"] = summary
        res["note"] = ("Playlist tracks get the names and colors. The mixer<->playlist "
                       "audio-track link ('Assign to new Audio track(s)') has no API.")
        return res

    @mcp.tool(annotations={"title": "Copy mixer names/colors to playlist", **_WR})
    def fl_mirror_playlist(
        first_mixer_track: Annotated[int, Field(ge=1)],
        last_mixer_track: Annotated[int, Field(ge=1)],
        first_playlist_track: Annotated[int, Field(ge=1)] = 1,
    ) -> dict:
        """Give playlist tracks the same names and colors as a range of mixer
        tracks, in order. ONE rollback unit."""
        b = get_bridge()
        rng = list(range(first_mixer_track, last_mixer_track + 1))
        items = fetch_all_pages(b, protocol.CMD_STATE_DUMP, "items",
                                params={"m": rng}).get("items", [])
        rows = []
        for n, it in enumerate(i for i in items if i[2] is not None):
            c = it[3]
            rows.append({"track": first_playlist_track + n, "name": it[2],
                         "color": ((c >> 16) & 255, (c >> 8) & 255, c & 255),
                         "raw": c})
        if not rows:
            return {"ok": False, "error": "no mixer tracks in that range"}
        writes = build_writes(playlist=[(r["track"], [["pn", r["track"], r["name"]],
                                                      ["pC", r["track"], r["raw"]]])
                                        for r in rows])
        res = safety.safe_write_group(b, tool="mirror_playlist", scope="organizer", writes=writes)
        if res.get("dry_run"):
            return res
        return {"ok": True, "playlist_tracks": [r["track"] for r in rows],
                "mismatches": _verify(b, [], rows), "undo": "fl_rollback_last_change"}
