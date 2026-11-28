"""fl_load_plugin: resolve the .fst on disk, walk the Browser, verify the result."""
import os

from fl_studio_mcp import protocol
from fl_studio_mcp.music import plugin_library as pl
from fl_studio_mcp.tools.loader import load_plugin


def _db(tmp_path):
    base = tmp_path / "Installed"
    for rel in ["Effects/VST3/Pro-Q 3.fst", "Effects/AU/Pro-Q 3.fst", "Effects/VST3/Pro-C 2.fst",
                "Effects/VST3/Pro-R 2.fst", "Generators/VST3/Serum.fst"]:
        f = base / rel
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_bytes(b"")
    return base


class FakeBridge:
    def __init__(self, load_after=1, works=True):
        self.slots = {0: "Fruity Limiter"}
        self.channels = 3
        self.calls = []
        self.pending = None
        self.load_after = load_after
        self.works = works

    def call(self, command, params=None, timeout=None):
        self.calls.append((command, params))
        if command == protocol.CMD_BROWSER_FIND:
            if self.works:
                self.pending = (params, self.load_after)
            return {"found": True, "confirmed": True}
        if self.pending:
            p, n = self.pending
            if n <= 0:
                if "track" in p:
                    self.slots[p["slot"]] = p["path"][-1]
                else:
                    self.channels += 1
                self.pending = None
            else:
                self.pending = (p, n - 1)
        if command == protocol.CMD_PLUGIN_LIST:
            return {"slots": [{"slot": s, "name": n} for s, n in self.slots.items()]}
        if command == protocol.CMD_SESSION_INFO:
            return {"channels": self.channels}
        raise AssertionError(command)


def test_resolve_prefers_vst3_and_builds_browser_path(tmp_path):
    res = pl.resolve_plugin("pro-q 3", base=str(_db(tmp_path)))
    assert res["exact"] and res["matches"][0]["path"] == [
        "Plugin database", "Installed", "Effects", "VST3", "Pro-Q 3"]


def test_effect_loads_into_first_free_slot_and_is_verified(tmp_path, monkeypatch):
    monkeypatch.setenv("FLSTUDIO_MCP_PLUGIN_DB", str(_db(tmp_path)))
    b = FakeBridge()
    res = load_plugin(b, "Pro-Q 3", track=4, sleep=lambda s: None)
    assert res["ok"] and res["slot"] == 1 and res["loaded"] == "Pro-Q 3"
    find = [p for c, p in b.calls if c == protocol.CMD_BROWSER_FIND][0]
    assert find["track"] == 4 and find["slot"] == 1 and find["confirm"] is True


def test_generator_becomes_new_channel(tmp_path, monkeypatch):
    monkeypatch.setenv("FLSTUDIO_MCP_PLUGIN_DB", str(_db(tmp_path)))
    res = load_plugin(FakeBridge(), "Serum", sleep=lambda s: None)
    assert res["ok"] and res["kind"] == "generator" and res["channel"] == 3


def test_never_claims_success_when_nothing_appears(tmp_path, monkeypatch):
    monkeypatch.setenv("FLSTUDIO_MCP_PLUGIN_DB", str(_db(tmp_path)))
    t = [0.0]
    monkeypatch.setattr("fl_studio_mcp.tools.loader.time.time", lambda: t[0])
    def fake_sleep(s):
        t[0] += 1.0
    res = load_plugin(FakeBridge(works=False), "Pro-Q 3", track=1, sleep=fake_sleep)
    assert res["ok"] is False


def test_ambiguous_name_asks_to_pick(tmp_path, monkeypatch):
    monkeypatch.setenv("FLSTUDIO_MCP_PLUGIN_DB", str(_db(tmp_path)))
    res = load_plugin(FakeBridge(), "Pro-", track=1, sleep=lambda s: None)
    assert res["ok"] is False and set(res["candidates"]) == {"Pro-Q 3", "Pro-C 2", "Pro-R 2"}


def test_effect_requires_track(tmp_path, monkeypatch):
    monkeypatch.setenv("FLSTUDIO_MCP_PLUGIN_DB", str(_db(tmp_path)))
    assert load_plugin(FakeBridge(), "Pro-C 2", sleep=lambda s: None)["ok"] is False
