# Roadmap

What is on `main`, what is next, and what FL Studio's scripting API rules out.
Tool names below are the real ones; the full list is in the README.

## Shipped

**Bridge and setup**
- MIDI SysEx bridge between the MCP server and a controller script inside FL Studio, with a heartbeat.
- `fl-studio-mcp setup`, `doctor` and `connect`; the controller script ships inside the package.
- macOS: the server creates its own MIDI ports and FL Studio links them by itself. Windows: loopMIDI.
- Several MCP clients can share one FL Studio: the first server owns the MIDI ports, the others join it.
- CI on Windows, macOS and Linux.

**Safety**
- Every write goes through snapshot → write → readback → rollback (`fl_rollback_last_change`).
- Undo is tied to the open project and controller session.
- Dry-run mode (`fl_set_dry_run`), verified plugin writes with retries, batch writes as one undo step.

**Tools (90)**
- Transport and tempo; project, mixer and channel state and writes.
- Mix Doctor, gain staging, full-song peak watch, reference match.
- EQ, compression, reverb and delay intents mapped to real plugin parameters.
- Plugin parameters by name, presets and chains from the installed library.
- Routing, grouping, bulk mute/solo, track and channel colours.
- Piano roll notes and quantize, scale/raga melody and chords, step sequencer, MIDI export.
- Patterns: list, select, rename, length, new, clone; timeline markers.
- Playlist tracks: list, mute, solo, rename, colour; arrangement selection and markers.
- Plugin deep control (also for channel-rack instruments): overview, parameter search, calibration to real units, set by real value, musical intents.
- Audio analysis: tempo and key, melody, chords and drums to MIDI.

## Next

1. **Release 2.0.0** to PyPI and the Official MCP Registry.
2. **Fewer, clearer tools.** Group the 90 tools by what they control (about 22), so they cost fewer tokens and are easier for a model to pick.
3. **Patcher presets as a plugin loader** (#39): the assistant writes a Patcher preset, you drag it in once, and it can then drive every exposed control.
4. **"What changed?"** A plain-language list of this session's changes, with undo for all of them.
5. **Larger replies in one round trip.** Replies are capped at about 600 bytes today, so long lists are paged.
6. **Simpler Windows setup.** Looking for a way to get the macOS no-click pairing with loopMIDI.

## Not possible through FL Studio's API

- Loading a plugin instance, loading an audio file, or rendering audio.
- Deleting patterns.
- Micro-tonal pitch: scales are rounded to the nearest semitone (12-tone MIDI).
- Running a piano-roll script without the user arming it once per session.
- More than one FL Studio instance on one machine is not wired up.

## fl-studio-mcp-21 (Franco / 21 Academy)

Hecho (2.1.0):
- Organizador en lote (`apply_ops` en el controlador): nombre, color, volumen y ruteo exclusivo del mixer; nombre y color de la playlist; nombre, color y destino de los canales.
- `fl_build_template`, `fl_organize_session`, `fl_mirror_playlist` y `fl_session_info`, todos con verificación y un solo paso para deshacer.

Siguiente:
- Probar en vivo qué funciones nuevas expone la API del mixer en FL 2025 (por ejemplo, para crear pistas o enlazarlas con la playlist) y usarlas si existen.
- Organizar una sesión de stems: detectar copias y RAW vs procesado, clasificar por nombre, mandar cada stem a su propio canal y agrupar en buses.
- Configuración inicial por productor (volumen por defecto, formato de exportación).
