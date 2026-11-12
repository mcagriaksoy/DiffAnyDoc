#!/bin/sh
# Per-user install of the DiffAnyDoc bundle (no root needed).
#   ./install.sh            install into ~/.local
#   ./install.sh --remove   uninstall
set -eu

HERE="$(cd "$(dirname "$0")" && pwd)"
PREFIX="${XDG_DATA_HOME:-$HOME/.local/share}"
TARGET="$HOME/.local/opt/DiffAnyDoc"
BIN="$HOME/.local/bin"

if [ "${1:-}" = "--remove" ]; then
    if [ -x "$TARGET/diffanydoc-cli" ]; then
        "$TARGET/diffanydoc-cli" integrate uninstall || true
    fi
    rm -f "$BIN/DiffAnyDoc" "$BIN/diffanydoc"
    rm -f "$PREFIX/applications/diffanydoc.desktop"
    rm -f "$PREFIX/icons/hicolor/512x512/apps/diffanydoc.png"
    # Only remove the folder this script installed, never a parent of it.
    case "$TARGET" in
        "$HOME"/.local/opt/DiffAnyDoc) rm -r -- "$TARGET" ;;
    esac
    echo "DiffAnyDoc removed."
    exit 0
fi

mkdir -p "$HOME/.local/opt" "$BIN" "$PREFIX/applications" "$PREFIX/icons/hicolor/512x512/apps"
if [ "$HERE" != "$TARGET" ]; then
    case "$TARGET" in
        "$HOME"/.local/opt/DiffAnyDoc) [ -d "$TARGET" ] && rm -r -- "$TARGET" ;;
    esac
    cp -R "$HERE" "$TARGET"
fi
ln -sf "$TARGET/DiffAnyDoc" "$BIN/DiffAnyDoc"
ln -sf "$TARGET/diffanydoc-cli" "$BIN/diffanydoc"
sed "s|^Exec=DiffAnyDoc|Exec=$TARGET/DiffAnyDoc|" "$TARGET/diffanydoc.desktop" \
    > "$PREFIX/applications/diffanydoc.desktop"
cp "$TARGET/diffanydoc.png" "$PREFIX/icons/hicolor/512x512/apps/diffanydoc.png"
"$TARGET/diffanydoc-cli" integrate install || true
command -v update-desktop-database >/dev/null 2>&1 && update-desktop-database "$PREFIX/applications" || true
echo "DiffAnyDoc installed. Start it from the application menu or run: DiffAnyDoc"
