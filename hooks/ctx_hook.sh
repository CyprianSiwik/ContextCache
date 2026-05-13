#!/bin/bash
# ctx_hook.sh — Claude Code PostToolUse hook for context_cache
#
# Receives tool events via stdin as JSON, routes to update_cache.py.
# Installed by scripts/install_hooks.py into ~/.claude/settings.json
#
# Env vars provided by Claude Code:
#   CLAUDE_TOOL_NAME   — e.g. "Write", "Edit", "Bash"
#   CLAUDE_TOOL_INPUT  — JSON string of tool input
#   CLAUDE_PROJECT_DIR — project root (set by install script)

TOOL="$CLAUDE_TOOL_NAME"
INPUT="$CLAUDE_TOOL_INPUT"
PROJECT_DIR="${CLAUDE_PROJECT_DIR:-$(pwd)}"
SCRIPT_DIR="$(dirname "$0")/../scripts"
CTX_SCRIPT="$SCRIPT_DIR/update_cache.py"

# Only run if update_cache.py exists
if [ ! -f "$CTX_SCRIPT" ]; then
  exit 0
fi

# Only run if a .ctx file exists in the project
if [ ! -f "$PROJECT_DIR/.ctx" ]; then
  exit 0
fi

# ── Write / Edit tool → --event write ────────────────────────────────────────
if [ "$TOOL" = "Write" ] || [ "$TOOL" = "Edit" ]; then
  FILE_PATH=$(echo "$INPUT" | python3 -c "
import sys, json
try:
    d = json.load(sys.stdin)
    print(d.get('file_path') or d.get('path') or '')
except:
    print('')
")
  if [ -n "$FILE_PATH" ]; then
    python3 "$CTX_SCRIPT" \
      --event write \
      --file "$FILE_PATH" \
      --ctx "$PROJECT_DIR/.ctx" \
      --root "$PROJECT_DIR" \
      2>/dev/null &
  fi

# ── Bash tool → parse for rm / mv / git commit ───────────────────────────────
elif [ "$TOOL" = "Bash" ]; then
  COMMAND=$(echo "$INPUT" | python3 -c "
import sys, json
try:
    d = json.load(sys.stdin)
    print(d.get('command') or '')
except:
    print('')
")

  # ── rm <file> → --event delete ─────────────────────────────────────────────
  if echo "$COMMAND" | grep -qE '^\s*rm\s'; then
    FILE_PATH=$(echo "$COMMAND" | python3 -c "
import sys, re
cmd = sys.stdin.read().strip()
# Match: rm [-flags] <path>  (single file, not -rf on dirs)
m = re.search(r'\brm\s+(?:-\w+\s+)*([^\s;|&]+\.[a-zA-Z0-9]+)', cmd)
print(m.group(1) if m else '')
")
    if [ -n "$FILE_PATH" ]; then
      python3 "$CTX_SCRIPT" \
        --event delete \
        --file "$FILE_PATH" \
        --ctx "$PROJECT_DIR/.ctx" \
        --root "$PROJECT_DIR" \
        2>/dev/null &
    fi

  # ── mv <old> <new> → --event rename ────────────────────────────────────────
  elif echo "$COMMAND" | grep -qE '^\s*mv\s'; then
    PATHS=$(echo "$COMMAND" | python3 -c "
import sys, re
cmd = sys.stdin.read().strip()
m = re.search(r'\bmv\s+(?:-\w+\s+)*([^\s;|&]+)\s+([^\s;|&]+)', cmd)
if m:
    print(m.group(1))
    print(m.group(2))
else:
    print('')
    print('')
")
    OLD_PATH=$(echo "$PATHS" | head -1)
    NEW_PATH=$(echo "$PATHS" | tail -1)
    if [ -n "$OLD_PATH" ] && [ -n "$NEW_PATH" ] && [ "$OLD_PATH" != "$NEW_PATH" ]; then
      python3 "$CTX_SCRIPT" \
        --event rename \
        --file "$OLD_PATH" \
        --new-file "$NEW_PATH" \
        --ctx "$PROJECT_DIR/.ctx" \
        --root "$PROJECT_DIR" \
        2>/dev/null &
    fi

  # ── git commit → --event git ───────────────────────────────────────────────
  elif echo "$COMMAND" | grep -qE 'git\s+commit'; then
    python3 "$CTX_SCRIPT" \
      --event git \
      --ctx "$PROJECT_DIR/.ctx" \
      --root "$PROJECT_DIR" \
      2>/dev/null &
  fi
fi

exit 0
