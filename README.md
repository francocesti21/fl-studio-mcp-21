# fl-studio-mcp-21

MCP para controlar **FL Studio** desde Claude, pensado para producir y enseñar con un criterio claro: **la IA no hace la parte creativa**. Solo se encarga de tareas repetitivas que se pueden delegar, como ordenar, nombrar, colorear y rutear, sin quitarle decisiones al productor.

Está basado en [rosasynthesiz/flstudio-mcp](https://github.com/rosasynthesiz/flstudio-mcp) (licencia MIT), con mejoras propias de 21 Academy. La documentación original está en [README_UPSTREAM.md](README_UPSTREAM.md).

## Primeros pasos (para productores)

1. Instala el MCP (ver *Instalación*, abajo) y abre FL Studio.
2. Descríbele tu template a Claude en el chat. Por ejemplo: *"10 canales de drums en rojo, 5 de melodías, 5 de voces, un bus por grupo, un bus INSTRUMENTAL y un MIXBUS"*.
3. Claude revisa cuántas pistas tiene tu mixer. Si faltan, te dice cuántas agregar: clic derecho en una pista → *Insert multiple* → escribes el número. FL no permite que un script cree pistas.
4. Claude arma todo el mixer en segundos: nombres, colores, buses y ruteo.
5. Claude selecciona los canales. Tú haces clic derecho en uno → *Assign to new Audio track(s)*, y quedan enlazados en la playlist, en orden.

Son unos 3 clics en total. Si tienes activado *computer use* en la app de escritorio de Claude, Claude puede hacer esos clics por ti, pero no es necesario.

**Consejo:** guarda como proyecto de inicio uno con unas 40 pistas en el mixer. Así nunca te faltan pistas y solo queda el clic de *Assign*. Y cuando tengas un template que te guste, guárdalo como plantilla de FL, con tus plugins ya cargados.

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

No trae una plantilla fija: cada productor describe la suya en el chat (grupos, cantidad de canales, colores, buses) y Claude la arma. Un ejemplo:

```
Drums 1-5, Melodías 1-5, Efectos 1-5  -> BUS DRUMS / BUS MELODÍAS / BUS EFECTOS -> INSTRUMENTAL ┐
Voces 1-5, Armonías 1-5               -> BUS VOCES / BUS ARMONÍAS               -> VOCES        ┴-> MIXBUS -> Master
```

## Enlazar con la playlist: un solo clic

`fl_mixer_select_tracks` selecciona los canales desde el script (probado en FL 2026). Después, en FL: clic derecho en uno de ellos → *Assign to new Audio track(s)*. Quedan todos enlazados en orden, con su nombre y color. Para que caigan desde el track 1, no nombres la playlist antes (`playlist=false`).

Crear pistas de mixer desde el script **no funciona** (probado: `ui.insert` y el comando global Insert no agregan pistas). Hay que usar *Mixer > Insert multiple*. Ojo: la última pista del mixer es un espacio oculto, así que necesitas una pista más de las que usa el template.

## Alternativa: canal LINK

Con `link_track="LINK"`, cada canal también envía al track LINK. Ese track no tiene salida, así que no se escucha nada. En FL:

1. Clic derecho en LINK → *Select* → *Tracks routed to this one*. Quedan seleccionados todos los canales.
2. Clic derecho en uno de ellos → *Assign to new Audio track(s)*. Todos quedan enlazados en la playlist, en orden, con su nombre y color.

Si vas a hacer esto, no nombres la playlist antes (`playlist=false`): FL considera ocupados los tracks con nombre y crea los tracks enlazados después de ellos.

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
