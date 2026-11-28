"""Read FL's installed-plugin DATABASE from disk -- bypasses the API wall.

FL writes a .fst shortcut for every scanned plugin under
  <Documents>/Image-Line/FL Studio*/Presets/Plugin database/Installed/
    Effects/<format>/*.fst      (FX)
    Generators/<format>/*.fst   (instruments)
The .fst BASENAME is the plugin name FL uses. We only read the directory listing
(names) -- never file contents. Read-only; pure filesystem. (FL still can't LOAD
these via the API directly; resolve_plugin() gives the Browser path that
tools/loader.py walks to load one.)
"""
from __future__ import annotations

import os

from ..paths import image_line_dirs

_ENV = "FLSTUDIO_MCP_PLUGIN_DB"     # override: full path to the 'Installed' folder

# Rough keyword buckets for EFFECTS, a convenience for chain suggestions. Fuzzy
# (a name can land in several roles); the full effects list stays authoritative.
_ROLE_KW = {
    "eq": ("equaliz", " eq", "eq ", "pro-q", "proq"),
    "compressor": ("compress", "pro-c", "proc", "vc 76", "vc76", "1176", "la-2a",
                   "opto", "glue", "dynamics", "comp"),
    "reverb": ("reverb", "reeverb", "verb", "rc 48", "rc48", "raum", " room",
               "hall", "plate"),
    "delay": ("delay", "echo", "replika"),
    "de-esser": ("de-ess", "deess", "de ess", "esser"),
    "saturation": ("saturat", "tape", "overdrive", "distort", "drive", "dirt",
                   "exciter", "decapitat", "clipper", "fresh air", "blood", "warmth"),
    "limiter": ("limiter", "maxim", "unlimit"),
    "pitch": ("auto-tune", "autotune", "auto-key", "pitch", "tuner", "newtone"),
    "width": ("imager", "stereo", "width", "widen", "spread"),
    "gate": ("gate", "expander"),
}


def find_plugin_db():
    """Locate FL's 'Installed' plugin-db folder: env override, else discover under
    the user's Documents (handles versioned 'FL Studio NN' folders)."""
    override = os.environ.get("FLSTUDIO_MCP_PLUGIN_DB")
    if override and os.path.isdir(override):
        return override
    for r in image_line_dirs():
        if not r.is_dir():
            continue
        for fl in sorted(r.glob("FL Studio*"), reverse=True):
            p = fl / "Presets" / "Plugin database" / "Installed"
            if p.is_dir():
                return str(p)
    return None


def _names(folder):
    out = set()
    if os.path.isdir(folder):
        for _root, _dirs, files in os.walk(folder):
            for f in files:
                if f.lower().endswith(".fst"):
                    out.add(os.path.splitext(f)[0])
    return out


def list_installed(base=None):
    """De-duped, categorized installed-plugin names:
    {found, path, effects:[...], generators:[...], counts}. Read-only."""
    base = base or find_plugin_db()
    if not base or not os.path.isdir(base):
        return {"found": False, "path": base,
                "error": "FL plugin-db 'Installed' folder not found; set %s to its path." % _ENV}
    eff = sorted(_names(os.path.join(base, "Effects")), key=str.lower)
    gen = sorted(_names(os.path.join(base, "Generators")), key=str.lower)
    return {"found": True, "path": base, "effects": eff, "generators": gen,
            "counts": {"effects": len(eff), "generators": len(gen)}}


def effects_by_role(effect_names):
    """ROUGH keyword grouping of effect names by mixing role (convenience for
    chain suggestions; fuzzy -- a name may land in several roles). Keywords are
    chosen so plain substring matching avoids obvious false positives (e.g. 'eq'
    uses ' eq'/'equaliz', never bare 'eq', so 'Frequency' isn't mis-bucketed)."""
    out = {role: [] for role in _ROLE_KW}
    for nm in effect_names:
        low = nm.lower()
        for role, kws in _ROLE_KW.items():
            if any(k in low for k in kws):
                out[role].append(nm)
    return {role: names for role, names in out.items() if names}


# Preferred formats when a plugin exists in several (macOS first, then Windows).
_FORMAT_ORDER = ("vst3", "au", "clap", "vst", "fruity", "new")


def resolve_plugin(name, kind="auto", base=None):
    """Find a plugin's .fst under Installed/ and return its Browser path.

    -> {found, matches:[{name, kind, format, path:[...captions...]}], exact}
    `path` starts at "Plugin database" (the Browser tree mirrors the folders).
    Exact (case-insensitive) name matches win; otherwise substring matches.
    """
    base = base or find_plugin_db()
    if not base or not os.path.isdir(base):
        return {"found": False, "error": "FL plugin-db 'Installed' folder not found; set %s." % _ENV}
    want = (name or "").strip().lower()
    kinds = {"effect": ("Effects",), "generator": ("Generators",)}.get(kind, ("Effects", "Generators"))
    exact, partial = [], []
    for top in kinds:
        root = os.path.join(base, top)
        for dirpath, _dirs, files in os.walk(root):
            for f in files:
                if not f.lower().endswith(".fst"):
                    continue
                stem = os.path.splitext(f)[0]
                rel = os.path.relpath(os.path.join(dirpath, stem), base).split(os.sep)
                entry = {"name": stem, "kind": "effect" if top == "Effects" else "generator",
                         "format": rel[1] if len(rel) > 2 else "",
                         "path": ["Plugin database", "Installed"] + rel}
                low = stem.lower()
                if low == want:
                    exact.append(entry)
                elif want and want in low:
                    partial.append(entry)

    def rank(e):
        fmt = e["format"].lower()
        return (_FORMAT_ORDER.index(fmt) if fmt in _FORMAT_ORDER else len(_FORMAT_ORDER), e["name"].lower())

    matches = sorted(exact, key=rank) or sorted(partial, key=rank)
    return {"found": bool(matches), "exact": bool(exact), "matches": matches[:12]}


def browser_skips(path, base=None):
    """Position of each path step among its folder's visible children in FL's
    Browser (subfolders first, then .fst presets; case-insensitive order), so
    the controller can jump instead of walking. skips[0] (the Browser root) is
    unknown -> None. Any step that can't be computed -> None (walk instead)."""
    base = base or find_plugin_db()
    if not base or len(path) < 2:
        return [None] * len(path)
    db_root = os.path.dirname(base)          # .../Plugin database
    skips = [None]
    folder = db_root
    for step in path[1:]:
        try:
            names = os.listdir(folder)
        except OSError:
            skips += [None] * (len(path) - len(skips))
            break
        dirs = sorted((n for n in names if os.path.isdir(os.path.join(folder, n))), key=str.lower)
        files = sorted((n[:-4] for n in names if n.lower().endswith(".fst")), key=str.lower)
        order = dirs + files
        low = [x.lower() for x in order]
        skips.append(low.index(step.lower()) if step.lower() in low else None)
        folder = os.path.join(folder, step)
    return skips
