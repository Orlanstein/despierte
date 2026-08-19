#!/bin/sh
# Instala despierte sin pip ni pipx: copia el paquete y crea un launcher.
# Pensado para Raspberry Pi OS (y cualquier Linux con python3), donde pipx
# no viene preinstalado y el proyecto no tiene dependencias de terceros
# que justifiquen un entorno virtual.
set -e

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
