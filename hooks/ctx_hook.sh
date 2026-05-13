#!/bin/bash
# ctx_hook.sh — Claude Code PostToolUse hook for ccache
#
# Receives tool event via stdin as JSON:
#   { "tool_name": "Write", "tool_input": {...}, ... }
#
# CLAUDE_PROJECT_DIR must be set (by install_hooks.py) to the project root.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CTX_SCRIPT="$SCRIPT_DIR/../scripts/update_cache.py"
PROJECT_DIR="${CLAUDE_PROJECT_DIR:-$(pwd)}"

if [ ! -f "$CTX_SCRIPT" ] || [ ! -f "$PROJECT_DIR/.ctx" ]; then
  exit 0
fi

# Write stdin to temp file so multiple Python calls can read it
TMPFILE=$(mktemp)
trap "rm -f $TMPFILE" EXIT
cat > "$TMPFILE"

TOOL=$(python3 -c "
import sys, json
with open(sys.argv[1]) as f:
    d = json.load(f)
print(d.get('tool_name', ''))
" "$TMPFILE" 2>/dev/null)

# ── Write / Edit → --event write ─────────────────────────────────────────────
if [ "$TOOL" = "Write" ] || [ "$TOOL" = "Edit" ]; then
  FILE_PATH=$(python3 -c "
import sys, json
with open(sys.argv[1]) as f:
    inp = json.load(f).get('tool_input', {})
print(inp.get('file_path') or inp.get('path') or '')
" "$TMPFILE" 2>/dev/null)
  if [ -n "$FILE_PATH" ]; then
    python3 "$CTX_SCRIPT" \
      --event write --file "$FILE_PATH" \
      --ctx "$PROJECT_DIR/.ctx" --root "$PROJECT_DIR" \
      2>/dev/null &
  fi

# ── Bash → parse for rm / mv / git commit ────────────────────────────────────
elif [ "$TOOL" = "Bash" ]; then
  COMMAND=$(python3 -c "
import sys, json
with open(sys.argv[1]) as f:
    inp = json.load(f).get('tool_input', {})
print(inp.get('command', ''))
" "$TMPFILE" 2>/dev/null)

  # rm <file> → --event delete
  if echo "$COMMAND" | grep -qE '^\s*rm\s'; then
    FILE_PATH=$(python3 -c "
import sys, re
cmd = sys.stdin.read().strip()
m = re.search(r'\brm\s+(?:-\w+\s+)*([^\s;|&]+\.[a-zA-Z0-9]+)', cmd)
print(m.group(1) if m else '')
" <<< "$COMMAND" 2>/dev/null)
    if [ -n "$FILE_PATH" ]; then
      python3 "$CTX_SCRIPT" \
        --event delete --file "$FILE_PATH" \
        --ctx "$PROJECT_DIR/.ctx" --root "$PROJECT_DIR" \
        2>/dev/null &
    fi

  # mv <old> <new> → --event rename
  elif echo "$COMMAND" | grep -qE '^\s*mv\s'; then
    PATHS=$(python3 -c "
import sys, re
cmd = sys.stdin.read().strip()
m = re.search(r'\bmv\s+(?:-\w+\s+)*([^\s;|&]+)\s+([^\s;|&]+)', cmd)
if m:
    print(m.group(1))
    print(m.group(2))
else:
    print('')
    print('')
" <<< "$COMMAND" 2>/dev/null)
    OLD_PATH=$(echo "$PATHS" | head -1)
    NEW_PATH=$(echo "$PATHS" | tail -1)
    if [ -n "$OLD_PATH" ] && [ -n "$NEW_PATH" ] && [ "$OLD_PATH" != "$NEW_PATH" ]; then
      python3 "$CTX_SCRIPT" \
        --event rename --file "$OLD_PATH" --new-file "$NEW_PATH" \
        --ctx "$PROJECT_DIR/.ctx" --root "$PROJECT_DIR" \
        2>/dev/null &
    fi

  # git commit → --event git
  elif echo "$COMMAND" | grep -qE 'git\s+commit'; then
    python3 "$CTX_SCRIPT" \
      --event git \
      --ctx "$PROJECT_DIR/.ctx" --root "$PROJECT_DIR" \
      2>/dev/null &
  fi
fi

exit 0
