# despierte

TUI (y CLI scriptable) para gestionar equipos por Wake-on-LAN: despertarlos,
ver si están online, y ejecutarles acciones por SSH. Escrito en Python 3 +
`curses` (librería estándar), sin dependencias de terceros — pensado para
correr liviano en una Raspberry Pi Zero 2 W.

## Instalación

No requiere pip ni pipx (ambos son opcionales, ver más abajo) **ni sudo** —
solo escribe dentro de tu `$HOME/.local`. Desde la raíz del repo:

```sh
./install.sh
# o: make install
```

No lo corras con `sudo`: con sudo `$HOME` pasa a ser `/root` y todo termina
instalado ahí en vez de en tu usuario. El script rechaza correr como root
para evitar justamente ese error.

Esto copia el paquete a `~/.local/lib/despierte` y crea un launcher ejecutable
en `~/.local/bin/despierte`. Si `~/.local/bin` no está en tu `PATH`, el script
te avisa cómo agregarlo.

Para desinstalar: `make uninstall`.

### Alternativa con pip/pipx (opcional)

Si ya tenés `pipx` instalado: `pipx install .`. Para desarrollo con un
entorno virtual: `python3 -m venv .venv && .venv/bin/pip install -e .`.

## Uso

Sin argumentos, `despierte` abre la TUI:

```sh
despierte
```

| Tecla | Acción |
|---|---|
| `↑↓` / `jk` | mover cursor |
| `espacio` | alternar selección |
| `a` / `A` | seleccionar todo / ninguno |
| `enter` / `w` | despertar seleccionados (o el del cursor) |
| `n` | nuevo equipo |
| `e` | editar equipo |
| `d` | borrar equipo(s) (con confirmación) |
| `s` | acciones SSH del equipo bajo el cursor |
| `r` | refrescar estado ahora |
| `/` | filtrar por nombre |
| `?` | ayuda |
| `q` | salir |

También funciona sin abrir la TUI, para scripting:

```sh
despierte list [--json]
despierte wake <nombre>... | --all
despierte status <nombre>              # exit code: 0 online, 1 offline, 2 desconocido
despierte add --name pc --mac AA:BB:CC:DD:EE:FF --ip 192.168.1.50
despierte edit <nombre> [mismos flags que add, solo los dados se actualizan]
despierte rm <nombre> [--yes]
despierte run <nombre> <acción> | --cmd "..." [--yes]
```

Todos los subcomandos aceptan `--config PATH` para usar un archivo de
configuración alternativo.

## Configuración

Los equipos se guardan en `~/.config/despierte/hosts.json` (o
`$XDG_CONFIG_HOME/despierte/hosts.json` si esa variable está definida).

## Prerrequisito para las acciones SSH

Las acciones remotas usan `ssh -o BatchMode=yes`, que falla rápido en vez de
pedir contraseña. Necesitás autenticación por clave ya configurada hacia los
equipos destino (`ssh-copy-id usuario@equipo`) — si no, la función va a
parecer que "simplemente no funciona".

## Alcance de Wake-on-LAN

Por defecto se envía el magic packet a `255.255.255.255` (broadcast
limitado), que funciona cuando el equipo que corre `despierte` y el
destino comparten segmento de red — el caso típico en una LAN doméstica.
Si tenés varias interfaces de red o el destino está en otra subred, podés
configurar una dirección de broadcast específica por equipo. Despertar a
través de routers/subredes distintas además requiere reenvío de broadcast
dirigido a nivel de router, fuera del alcance de esta herramienta.

## Tests

```sh
make test
# o: python3 -m unittest discover -s tests
```

Cubre la construcción del magic packet, el guardado/carga de configuración,
los validadores de MAC/IP, el chequeo de estado (mockeando `ping`), la
ejecución de acciones SSH (mockeando `ssh`) y el CLI. La TUI en sí (colores,
formularios, redibujado) requiere una terminal real y se verifica a mano.
