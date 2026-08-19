#!/bin/sh
# Instala despierte sin pip ni pipx: copia el paquete y crea un launcher.
# Pensado para Raspberry Pi OS (y cualquier Linux con python3), donde pipx
# no viene preinstalado y el proyecto no tiene dependencias de terceros
# que justifiquen un entorno virtual.
set -e

if [ "$(id -u)" -eq 0 ] && [ -z "$PREFIX" ]; then
    echo "error: no corras install.sh con sudo — no hace falta, solo escribe en tu \$HOME/.local." >&2
    echo "       corrido con sudo, quedaría instalado en /root en vez de tu usuario." >&2
    echo "       corré: ./install.sh (sin sudo)" >&2
    exit 1
fi

PREFIX="${PREFIX:-$HOME/.local}"
LIBDIR="$PREFIX/lib/despierte"
BINDIR="$PREFIX/bin"
SRC_DIR="$(cd "$(dirname "$0")" && pwd)/despierte"

if [ ! -d "$SRC_DIR" ]; then
    echo "error: no se encontró $SRC_DIR (¿corriste install.sh desde la raíz del repo?)" >&2
    exit 1
fi

mkdir -p "$LIBDIR" "$BINDIR"
rm -rf "$LIBDIR/despierte"
cp -r "$SRC_DIR" "$LIBDIR/despierte"

cat > "$BINDIR/despierte" <<EOF
#!/usr/bin/env python3
import sys
sys.path.insert(0, "$LIBDIR")
from despierte.cli import main

if __name__ == "__main__":
    sys.exit(main())
EOF
chmod +x "$BINDIR/despierte"

echo "instalado en $BINDIR/despierte"
case ":$PATH:" in
    *":$BINDIR:"*) ;;
    *)
        echo "aviso: $BINDIR no está en tu PATH. Agregá esto a tu ~/.bashrc o ~/.zshrc:"
        echo "  export PATH=\"$BINDIR:\$PATH\""
        ;;
esac
