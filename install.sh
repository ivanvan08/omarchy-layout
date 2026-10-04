#!/usr/bin/env bash
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

PLUGIN_SRC="$REPO_DIR/plugin"
PLUGIN_DST="$HOME/.config/omarchy/plugins/omarchy-layout"

CLI_SRC="$REPO_DIR/bin/layout"
CLI_DST="$HOME/.local/bin/omarchy-layout"

HYPR_SRC="$REPO_DIR/hypr/omarchy-layout.lua"
HYPR_DST="$HOME/.config/hypr/omarchy-layout.lua"

usage() {
  cat <<'EOF'
Usage: install.sh [--uninstall]

Symlinks the omarchy-layout plugin, CLI, and Hyprland layout into the user
config. With --uninstall, removes those three symlinks only.
EOF
}

link() {
  local src="$1" dst="$2"
  if [ ! -e "$src" ]; then
    echo "install.sh: source missing: $src" >&2
    exit 1
  fi
  mkdir -p "$(dirname "$dst")"
  ln -sfn "$src" "$dst"
  echo "  linked $dst -> $src"
}

unlink() {
  local dst="$1"
  if [ -L "$dst" ]; then
    rm -f "$dst"
    echo "  removed $dst"
  else
    echo "  skipped $dst (not a symlink)"
  fi
}

UNINSTALL=0
for arg in "$@"; do
  case "$arg" in
    --uninstall) UNINSTALL=1 ;;
    -h|--help) usage; exit 0 ;;
    *) echo "install.sh: unknown argument: $arg" >&2; usage >&2; exit 2 ;;
  esac
done

if [ "$UNINSTALL" -eq 1 ]; then
  echo "Removing omarchy-layout symlinks:"
  unlink "$PLUGIN_DST"
  unlink "$CLI_DST"
  unlink "$HYPR_DST"
  echo
  echo "Done. Remove the omarchy-layout dofile line from ~/.config/hypr/hyprland.lua,"
  echo "then run: omarchy-shell shell rescanPlugins"
  exit 0
fi

echo "Installing omarchy-layout from $REPO_DIR:"
link "$PLUGIN_SRC" "$PLUGIN_DST"
link "$CLI_SRC" "$CLI_DST"
link "$HYPR_SRC" "$HYPR_DST"
echo
echo "Done. Two manual steps remain:"
echo "  1. Add this line to ~/.config/hypr/hyprland.lua:"
echo "       dofile((os.getenv(\"HOME\") or \"\") .. \"/.config/hypr/omarchy-layout.lua\")"
echo "  2. Reload the plugin: omarchy-shell shell rescanPlugins"
