#!/usr/bin/env bash
set -euo pipefail

AGENTS_DIR="${HOME}/.claude/agents"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"

TOOL=""
CATEGORY=""

usage() {
  cat <<EOF
Usage: $(basename "$0") [OPTIONS]

Install Claude Code agents to ~/.claude/agents/

Options:
  --tool <name>       Target tool installation (currently: claude-code)
  --category <name>   Install only a specific category directory (e.g. engineering)
  -h, --help          Show this help message

Examples:
  $(basename "$0") --tool claude-code
  $(basename "$0") --tool claude-code --category engineering
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --tool)
      TOOL="$2"; shift 2 ;;
    --category)
      CATEGORY="$2"; shift 2 ;;
    -h|--help)
      usage; exit 0 ;;
    *)
      echo "Unknown option: $1" >&2; usage; exit 1 ;;
  esac
done

if [[ -z "$TOOL" ]]; then
  echo "Error: --tool is required" >&2
  usage
  exit 1
fi

if [[ "$TOOL" != "claude-code" ]]; then
  echo "Error: unsupported tool '$TOOL'. Supported: claude-code" >&2
  exit 1
fi

mkdir -p "$AGENTS_DIR"

install_category() {
  local category="$1"
  local src_dir="${REPO_DIR}/${category}"

  if [[ ! -d "$src_dir" ]]; then
    echo "Warning: category directory not found: ${src_dir}" >&2
    return 1
  fi

  local count=0
  while IFS= read -r -d '' agent_file; do
    local filename
    filename="$(basename "$agent_file")"
    local dest="${AGENTS_DIR}/${filename}"

    if [[ -f "$dest" ]]; then
      echo "  [skip]    ${filename} (already exists — use --force to overwrite)"
    else
      cp "$agent_file" "$dest"
      echo "  [install] ${filename}"
      count=$((count + 1))
    fi
  done < <(find "$src_dir" -maxdepth 1 -name "*.md" -print0 | sort -z)

  echo "  Installed ${count} agent(s) from '${category}'"
}

echo "Installing agents for tool: ${TOOL}"
echo "Destination: ${AGENTS_DIR}"
echo ""

if [[ -n "$CATEGORY" ]]; then
  install_category "$CATEGORY"
else
  installed_total=0
  while IFS= read -r -d '' category_dir; do
    category="$(basename "$category_dir")"
    echo "Category: ${category}"
    install_category "$category"
    echo ""
  done < <(find "$REPO_DIR" -mindepth 1 -maxdepth 1 -type d -not -name ".*" -not -name "scripts" -print0 | sort -z)
fi

echo "Done. Activate any agent in Claude Code:"
echo '  "activate <agent-name> mode"'
echo ""
echo "Available agents:"
find "$AGENTS_DIR" -name "*.md" | sort | while read -r f; do
  name="$(basename "$f" .md)"
  echo "  - ${name}"
done
