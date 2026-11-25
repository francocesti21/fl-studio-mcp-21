# fl-studio-mcp-21

MCP para controlar **FL Studio** desde Claude, pensado para producir y enseñar con un criterio claro: **la IA no hace la parte creativa**. Solo se encarga de tareas repetitivas que se pueden delegar, como ordenar, nombrar, colorear y rutear, sin quitarle decisiones al productor.

Está basado en [rosasynthesiz/flstudio-mcp](https://github.com/rosasynthesiz/flstudio-mcp) (licencia MIT), con mejoras propias de 21 Academy. La documentación original está en [README_UPSTREAM.md](README_UPSTREAM.md).

## Qué agrega esta versión

| Herramienta | Qué hace |
|---|---|
| `fl_build_template` | Arma una plantilla completa en una sola llamada. Crea los canales numerados por grupo con un degradado arcoíris, un bus por grupo, buses intermedios (INSTRUMENTAL / VOCES) y un MIXBUS que va al Master. También nombra y colorea la playlist igual que el mixer. Con `preview=true` solo muestra el plan, sin cambiar nada. |
| `fl_organize_session` | Cambia en lote los nombres, colores, volumen (dB) y ruteo exclusivo del mixer, los nombres y colores de la playlist, y los nombres, colores y pista de mixer de los canales del Channel Rack. |
| `fl_mirror_playlist` | Copia los nombres y colores de un rango de pistas del mixer a la playlist, en el mismo orden. |
| `fl_session_info` | Muestra cuántas pistas de mixer, de playlist y canales tiene el proyecto. |

Todas estas herramientas:
- **Verifican** el resultado volviendo a leer el estado de FL después de aplicar los cambios.
- **Se deshacen en un paso** con `fl_rollback_last_change`.
- Viajan en mensajes chicos por MIDI (SysEx). Una plantilla de 33 pistas tarda segundos, sin clics en pantalla.

La plantilla por defecto es la de Franco:

```
Drums 1-5, Melodías 1-5, Efectos 1-5  -> BUS DRUMS / BUS MELODÍAS / BUS EFECTOS -> INSTRUMENTAL ┐
Voces 1-5, Armonías 1-5               -> BUS VOCES / BUS ARMONÍAS               -> VOCES        ┴-> MIXBUS -> Master
```

## Límites de FL Studio (no son errores del MCP)

La API de scripts de FL **no permite** lo siguiente:
- **Crear pistas de mixer.** `fl_build_template` revisa antes cuántas hay y te dice cuántas agregar desde *Mixer > Insert multiple*.
- **"Assign to new Audio track(s)"**, es decir, el enlace entre mixer y playlist. La playlist queda con los mismos nombres y colores, pero sin ese enlace.
- **Anclar pistas a la izquierda o derecha.** La API solo permite leer de qué lado están.
- **Cargar plugins o presets.** Solo se pueden controlar los plugins que ya están cargados en el proyecto.

## Instalación (macOS)

```bash
git clone https://github.com/francocesti21/fl-studio-mcp-21 ~/fl-studio-mcp-21
cd ~/fl-studio-mcp-21
./scripts/install_macos.sh
```

Después, en `claude_desktop_config.json`:

```json
"fl-studio": {
  "command": "/Users/TU_USUARIO/fl-studio-mcp-21/.venv/bin/fl-studio-mcp",
  "env": {"FLSTUDIO_MCP_TRANSPORT": "tcp"}
}
```

Reinicia FL Studio y Claude. Para comprobar que todo funciona, ejecuta `fl_ping`.

## Privacidad

Este MCP no envía telemetría. Todo ocurre en tu computadora: Claude se comunica con FL Studio por MIDI local.

## Licencia

MIT. Mantiene el copyright del proyecto original (ver [LICENSE](LICENSE)).
