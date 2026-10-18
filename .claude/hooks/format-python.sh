#!/usr/bin/env bash
# PostToolUse hook: format an edited Python file under backend/ with ruff.
# Never blocks the agent: any problem is ignored (CI and pr-ready enforce formatting).
set -u
file=$(python3 -c 'import json,sys; print(json.load(sys.stdin).get("tool_input",{}).get("file_path",""))' 2>/dev/null) || exit 0
case "$file" in
  */backend/*.py) ;;
  *) exit 0 ;;
esac
root="${CLAUDE_PROJECT_DIR:-.}/backend"
[ -f "$root/pyproject.toml" ] && command -v uv >/dev/null 2>&1 || exit 0
( cd "$root" && uv run --quiet ruff format "$file" >/dev/null 2>&1 ) || true
exit 0
