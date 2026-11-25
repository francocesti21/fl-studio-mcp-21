"""fl-studio-mcp-21 organizer: plan, apply through the REAL controller script
against a simulated FL project, verify, and undo in one step."""
from __future__ import annotations

import pytest

from fl_studio_mcp import safety
from fl_studio_mcp.tools import organizer as org


class SimFL:
    """Just enough of FL's mixer/playlist/channels state for the organizer."""

    def __init__(self, mixer_tracks=40, playlist_tracks=30, chans=3):
        self.m_names = ["Master"] + ["Insert %d" % i for i in range(1, mixer_tracks)]
        self.m_colors = [0x565656] * mixer_tracks
        self.m_vol = [0.8] * mixer_tracks
        self.routes = {i: {0} for i in range(1, mixer_tracks)}
        self.routes[0] = set()
        self.p_names = [""] + ["Track %d" % i for i in range(1, playlist_tracks + 1)]
        self.p_colors = [0x484848] * (playlist_tracks + 1)
        self.c_names = ["Ch %d" % i for i in range(chans)]
        self.c_colors = [0x333333] * chans
        self.c_target = [0] * chans
        self.routing_commits = 0


def install(controller, sim):
    mx, pl, ch, gen, ut = (controller.mixer, controller.playlist, controller.channels,
                           controller.general, controller.utils)
    mx.trackCount = lambda: len(sim.m_names)
    mx.getTrackName = lambda i: sim.m_names[i]
    mx.setTrackName = lambda i, n: sim.m_names.__setitem__(i, n)
    mx.getTrackColor = lambda i: sim.m_colors[i]
    mx.setTrackColor = lambda i, c: sim.m_colors.__setitem__(i, c)
    mx.getTrackVolume = lambda i: sim.m_vol[i]
    mx.setTrackVolume = lambda i, v: sim.m_vol.__setitem__(i, v)
    mx.getRouteSendActive = lambda s, d: d in sim.routes.get(s, set())

    def set_route(s, d, on):
        (sim.routes.setdefault(s, set()).add if on else sim.routes.setdefault(s, set()).discard)(d)
    mx.setRouteTo = set_route
    mx.afterRoutingChanged = lambda: setattr(sim, "routing_commits", sim.routing_commits + 1)
    pl.trackCount = lambda: len(sim.p_names) - 1
    pl.getTrackName = lambda t: sim.p_names[t]
    pl.setTrackName = lambda t, n: sim.p_names.__setitem__(t, n)
    pl.getTrackColor = lambda t: sim.p_colors[t]
    pl.setTrackColor = lambda t, c: sim.p_colors.__setitem__(t, c)
    ch.channelCount = lambda: len(sim.c_names)
    ch.getChannelName = lambda i: sim.c_names[i]
    ch.setChannelName = lambda i, n: sim.c_names.__setitem__(i, n)
    ch.getChannelColor = lambda i: sim.c_colors[i]
    ch.setChannelColor = lambda i, c: sim.c_colors.__setitem__(i, c)
    ch.getTargetFxTrack = lambda i: sim.c_target[i]
    ch.setTargetFxTrack = lambda i, t: sim.c_target.__setitem__(i, t)
    gen.getVersion = lambda: 40
    ut.RGBToColor = lambda r, g, b: (r << 16) | (g << 8) | b


class ControllerBridge:
    """Routes bridge calls into the real controller's dispatcher."""

    def __init__(self, controller):
        self.c = controller
        self.calls = []

    def call(self, command, params=None):
        params = dict(params or {})
        self.calls.append(command)
        if command == "get_project_state":
            return {"project_token": "sim", "project_loading": False}
        params.pop("_project_token", None)
        params.pop("_expected_pattern", None)
        return self.c._HANDLERS[command](params)


@pytest.fixture
def sim_env(controller, changelog, monkeypatch):
    sim = SimFL()
    install(controller, sim)
    bridge = ControllerBridge(controller)
    monkeypatch.setattr(org, "get_bridge", lambda: bridge)
    monkeypatch.setattr(safety, "_project_token_of", lambda b: "sim", raising=False)
    return sim, bridge


def test_rainbow_endpoints():
    cols = org.rainbow(25)
    assert len(cols) == 25
    assert org.hex_of(cols[0]) == "#F22C2C"
    assert org.hex_of(cols[-1]) == "#C12CF2"


def test_plan_matches_franco_template():
    plan = org.plan_template(org.EXAMPLE_GROUPS)
    by = {r["track"]: r for r in plan["mixer"]}
    assert by[1]["name"] == "Drums 1" and by[25]["name"] == "Armonías 5"
    assert [by[t]["name"] for t in range(26, 34)] == [
        "BUS DRUMS", "BUS MELODÍAS", "BUS EFECTOS", "BUS VOCES", "BUS ARMONÍAS",
        "INSTRUMENTAL", "VOCES", "MIXBUS"]
    assert by[1]["route_to"] == [26] and by[25]["route_to"] == [30]
    assert by[26]["route_to"] == by[27]["route_to"] == by[28]["route_to"] == [31]
    assert by[29]["route_to"] == by[30]["route_to"] == [32]
    assert by[31]["route_to"] == by[32]["route_to"] == [33]
    assert by[33]["route_to"] == [0]
    assert len(plan["playlist"]) == 25
    assert plan["playlist"][0] == {"track": 1, "name": "Drums 1", "color": by[1]["color"]}
    assert plan["last_track"] == 33


def _tool(name):
    from fastmcp import FastMCP
    mcp = FastMCP("t")
    org.register(mcp)
    import asyncio
    tool = asyncio.run(mcp.get_tool(name))
    return getattr(tool, "fn", tool)


def test_build_template_applies_verifies_and_undoes(sim_env):
    sim, bridge = sim_env
    before = (list(sim.m_names), list(sim.m_colors), {k: set(v) for k, v in sim.routes.items()},
              list(sim.p_names), list(sim.p_colors))
    res = _tool("fl_build_template")(groups=[org.GroupSpec(**g) for g in org.EXAMPLE_GROUPS])
    assert res["ok"], res
    assert res["mismatches"] == [] and res["errors"] == []
    assert sim.m_names[1] == "Drums 1" and sim.m_names[33] == "MIXBUS"
    assert sim.routes[1] == {26} and sim.routes[29] == {32} and sim.routes[33] == {0}
    assert sim.p_names[1] == "Drums 1" and sim.p_names[25] == "Armonías 5"
    assert sim.p_colors[1] == sim.m_colors[1] == 0xF22C2C
    assert sim.routing_commits > 0

    out = safety.rollback_last_change(bridge)
    assert out.get("ok"), out
    after = (sim.m_names, sim.m_colors, sim.routes, sim.p_names, sim.p_colors)
    assert after[0] == before[0] and after[1] == before[1]
    assert {k: v for k, v in after[2].items()} == before[2]
    assert after[3] == before[3] and after[4] == before[4]


def test_template_refuses_when_mixer_too_small(controller, changelog, monkeypatch):
    sim = SimFL(mixer_tracks=26)
    install(controller, sim)
    bridge = ControllerBridge(controller)
    monkeypatch.setattr(org, "get_bridge", lambda: bridge)
    res = _tool("fl_build_template")(groups=[org.GroupSpec(**g) for g in org.EXAMPLE_GROUPS])
    assert res["ok"] is False and res["add"] == 8
    assert sim.m_names[1] == "Insert 1"          # nothing written


def test_preview_changes_nothing(sim_env):
    sim, _ = sim_env
    res = _tool("fl_build_template")(groups=[org.GroupSpec(**g) for g in org.EXAMPLE_GROUPS], preview=True)
    assert res["preview"] and len(res["mixer"]) == 33
    assert sim.m_names[1] == "Insert 1"


def test_organize_session_channels_and_mirror(sim_env):
    sim, bridge = sim_env
    res = _tool("fl_organize_session")(
        mixer=[org.MixerTrackSpec(track=5, name="Kick", color="red", volume_db=-6, route_to=[10])],
        channels=[org.ChannelSpec(channel=1, name="Kick", color="#00FF00", mixer_track=5)],
        mirror_playlist=True)
    assert res["ok"], res
    assert sim.m_names[5] == "Kick" and sim.routes[5] == {10}
    assert abs(sim.m_vol[5] - 0.8 * 10 ** (-6 / 20)) < 1e-6
    assert sim.c_names[1] == "Kick" and sim.c_target[1] == 5 and sim.c_colors[1] == 0x00FF00
    assert sim.p_names[1] == "Kick"
    safety.rollback_last_change(bridge)
    assert sim.m_names[5] == "Insert 5" and sim.routes[5] == {0}
    assert sim.c_names[1] == "Ch 1" and sim.c_target[1] == 0 and sim.p_names[1] == "Track 1"


def test_every_request_fits_sysex_budget():
    plan = org.plan_template(org.EXAMPLE_GROUPS)
    for r in plan["mixer"]:
        ops = org.mixer_ops(r["track"], r["name"], r["color"], None, r["route_to"])
        assert org._chunks_ok(ops)
    long_restore = org.restore_ops(["m", 3, "x" * 32, 0xFFFFFF, 0.8, list(range(4, 20))])
    assert org._chunks_ok(long_restore)
