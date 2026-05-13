# Claude Code Hooks Integration

Automatic `.ctx` updates via Claude Code's `PostToolUse` hook system.
Once installed, the cache updates itself — no manual `update_cache.py` calls needed.

---

## Install

```bash
# From your project root (after running init_cache.py)
python path/to/ccache/scripts/install_hooks.py --project-dir .
```

This writes three hook entries into `~/.claude/settings.json` and backs up the
existing file to `~/.claude/settings.json.bak`.

## Uninstall

```bash
python scripts/install_hooks.py --uninstall
```

---

## What Gets Hooked

| Claude Code Tool | Trigger | Cache Event |
|-----------------|---------|-------------|
| `Write` | File created or overwritten | `--event write` |
| `Edit` | File patched | `--event write` (re-analyze) |
| `Bash` with `rm` | File deleted | `--event delete` |
| `Bash` with `mv` | File renamed/moved | `--event rename` |
| `Bash` with `git commit` | Commit made | `--event git` |

All hooks run **after** the tool completes (`PostToolUse`) and are
**non-blocking** — they run in the background so they never slow Claude down.

---

## How It Works

`hooks/ctx_hook.sh` receives the tool name and input JSON as env vars from
Claude Code. It parses the input to extract file paths, then calls
`update_cache.py` with the appropriate event flag.

The hook script is a no-op if:
- No `.ctx` file exists in the project directory
- `update_cache.py` is not found at the expected path

So it's safe to install globally — it only activates in projects that have
been initialized with `init_cache.py`.

---

## Multiple Projects

Run `install_hooks.py` once per project with `--project-dir` pointing to each
project root. Each install adds hooks scoped to that specific project directory.

```bash
# Project A
python scripts/install_hooks.py --project-dir ~/code/project-a

# Project B
python scripts/install_hooks.py --project-dir ~/code/project-b
```

Each hook entry has a unique ID (`ccache_write`, `ccache_bash`,
etc.) — re-running install for the same project replaces existing entries
rather than duplicating them.

---

## Troubleshooting

**Hooks not firing:**
- Check `~/.claude/settings.json` contains the hook entries
- Verify `hooks/ctx_hook.sh` is executable: `chmod +x hooks/ctx_hook.sh`
- Confirm `.ctx` exists in the project root

**Cache not updating after `rm`:**
- The hook matches `rm <file>` but not `rm -rf <directory>`
- Directory deletions require a manual `--event full` re-scan

**Wrong project dir:**
- Re-run `install_hooks.py --project-dir <correct-path>` to overwrite
