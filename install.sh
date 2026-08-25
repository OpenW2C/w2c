#!/usr/bin/env bash
# Install the W2C CLI + agent skills (copy payload, not a symlink).
set -euo pipefail

usage() {
  cat <<'EOF'
Usage:
  install.sh [--dry-run] [--force] [--skip-skills] [--no-cursor] [--no-claude]

Copies this checkout (or a fresh clone of OpenW2C/w2c) to
$XDG_DATA_HOME/w2c (default: ~/.local/share/w2c) and writes a PATH shim at
~/.local/bin/w2c. Then installs work-to-chores / do-chores into
~/.agents/skills unless --skip-skills.

Piped install:
  curl -fsSL https://raw.githubusercontent.com/OpenW2C/w2c/main/install.sh | bash
EOF
}

die() { printf 'Error: %s\n' "$1" >&2; exit 1; }
info() { printf '[w2c-install] %s\n' "$1"; }

DRY_RUN=0
FORCE=0
SKIP_SKILLS=0
NO_CURSOR=0
NO_CLAUDE=0
REPO_URL="${W2C_REPO_URL:-https://github.com/OpenW2C/w2c.git}"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --dry-run) DRY_RUN=1; shift ;;
    --force) FORCE=1; shift ;;
    --skip-skills) SKIP_SKILLS=1; shift ;;
    --no-cursor) NO_CURSOR=1; shift ;;
    --no-claude) NO_CLAUDE=1; shift ;;
    -h|--help) usage; exit 0 ;;
    *) die "Unknown argument: $1" ;;
  esac
done

resolve_source() {
  local src="${BASH_SOURCE[0]:-}"
  if [[ -n "$src" && -f "$src" && "$src" != /dev/fd/* && "$src" != /proc/self/fd/* ]]; then
    local dir
    dir="$(cd "$(dirname "$src")" && pwd)"
    if [[ -d "$dir/src/w2c" && -d "$dir/templates" && -d "$dir/skills" ]]; then
      printf '%s\n' "$dir"
      return 0
    fi
  fi
  return 1
}

SOURCE=""
CLEANUP=""
if SOURCE="$(resolve_source)"; then
  :
else
  command -v git >/dev/null 2>&1 || die "git is required to clone OpenW2C/w2c"
  CLEANUP="$(mktemp -d)"
  git clone --depth 1 "$REPO_URL" "$CLEANUP/w2c"
  SOURCE="$CLEANUP/w2c"
fi
[[ -d "$SOURCE/src/w2c" ]] || die "missing $SOURCE/src/w2c"
[[ -d "$SOURCE/templates" ]] || die "missing $SOURCE/templates"
[[ -d "$SOURCE/skills" ]] || die "missing $SOURCE/skills"

DATA_HOME="${W2C_DATA_HOME:-${XDG_DATA_HOME:-$HOME/.local/share}/w2c}"
BIN_DIR="${W2C_BIN_DIR:-$HOME/.local/bin}"
CONFIG_DIR="${W2C_CONFIG_DIR:-${XDG_CONFIG_HOME:-$HOME/.config}/.w2c}"
SHIM="$BIN_DIR/w2c"

if [[ "$DRY_RUN" == 1 ]]; then
  info "would copy $SOURCE/{src,templates,skills,scripts} -> $DATA_HOME"
  info "would write $SHIM"
  info "would mkdir $CONFIG_DIR"
  [[ "$SKIP_SKILLS" == 1 ]] || info "would install skills into ~/.agents/skills"
  [[ -n "$CLEANUP" ]] && rm -rf "$CLEANUP"
  exit 0
fi

mkdir -p "$DATA_HOME/src" "$DATA_HOME/templates" "$DATA_HOME/skills" "$DATA_HOME/scripts" "$BIN_DIR" "$CONFIG_DIR"

if [[ "$FORCE" == 1 ]]; then
  rm -rf "$DATA_HOME/src" "$DATA_HOME/templates" "$DATA_HOME/skills" "$DATA_HOME/scripts"
  mkdir -p "$DATA_HOME/src" "$DATA_HOME/templates" "$DATA_HOME/skills" "$DATA_HOME/scripts"
fi

cp -R "$SOURCE/src/." "$DATA_HOME/src/"
cp -R "$SOURCE/templates/." "$DATA_HOME/templates/"
cp -R "$SOURCE/skills/." "$DATA_HOME/skills/"
cp -R "$SOURCE/scripts/." "$DATA_HOME/scripts/"
find "$DATA_HOME" -name '__pycache__' -type d -exec rm -rf {} + 2>/dev/null || true
find "$DATA_HOME" -name '*.pyc' -delete 2>/dev/null || true
chmod +x "$DATA_HOME/scripts/w2c.py" "$DATA_HOME/scripts/w2c.sh" \
  "$DATA_HOME/scripts/w2c-smoke.py" "$DATA_HOME/scripts/w2c-smoke.sh" 2>/dev/null || true

cat > "$SHIM" <<EOF
#!/usr/bin/env bash
export PYTHONPATH="$DATA_HOME/src"
exec python3 -m w2c "\$@"
EOF
chmod +x "$SHIM"

if [[ ! -f "$CONFIG_DIR/config.toml" ]]; then
  printf '%s\n' '# W2C global config' 'projects = [' ']' '' > "$CONFIG_DIR/config.toml"
fi

if [[ "$SKIP_SKILLS" != 1 ]]; then
  skill_args=(install-skills)
  [[ "$FORCE" == 1 ]] && skill_args+=(--force)
  [[ "$NO_CURSOR" == 1 ]] && skill_args+=(--no-cursor)
  [[ "$NO_CLAUDE" == 1 ]] && skill_args+=(--no-claude)
  PYTHONPATH="$DATA_HOME/src" python3 -m w2c "${skill_args[@]}"
fi

[[ -n "$CLEANUP" ]] && rm -rf "$CLEANUP"

info "installed CLI payload at $DATA_HOME"
info "shim: $SHIM"
case ":$PATH:" in
  *":$BIN_DIR:"*) ;;
  *) info "warning: $BIN_DIR is not on PATH; add it so \`w2c\` resolves" ;;
esac
