---
name: ccache
description: >
  Persistent, compressed project context cache. Only activate when the user
  explicitly invokes it — via /ccache, or phrases like "orient around this
  codebase", "load the cache", "refresh context", "update the cache", "init
  cache", or "what does the cache say". Also triggers when the user asks Claude
  to remember something about the project architecture, mark a todo, or leave a
  note for next session. Use after any file creation, deletion, or rename to
  keep the cache current. Do NOT auto-activate on session start — wait for
  explicit invocation.
---

# ccache

A token-efficient, self-updating project context system. One `.ctx` file at the
project root gives Claude a compressed snapshot of the codebase — invoke it when
you want Claude to orient around the full project rather than work on specific files.

## Callword

Invoke this skill explicitly:

```
/ccache
"orient around this codebase"
"load the cache"
```

Skip it when you're working on one or two known files — Claude doesn't need the
cache to fix a specific function or edit a known path.

## How It Works

- **`.ctx`** — compressed project snapshot (custom shorthand format; see schema below)
- **`.ctxconfig`** — optional config (what to include/exclude, auto-update triggers)
- **`scripts/init_cache.py`** — generate the initial cache from scratch
- **`scripts/update_cache.py`** — patch the cache on individual file events
- **`references/schema.md`** — full format spec (load this when you need to hand-write or debug a `.ctx` block)

---

## On Invocation

When the skill is explicitly called:

1. Look for `.ctx` in the project root (or walk up to find the nearest one).
2. If found: read it fully. This is your project state. You now know the file
   tree, exports, dependencies, git state, and any notes left by previous sessions.
   Do not re-scan files already in the cache unless the user asks you to look
   deeper at a specific file.
3. If not found: offer to run `init_cache.py` to create it. Ask for the project
   root path if not obvious.
4. After reading, briefly confirm what you loaded:
   > "Loaded context cache — `my-api`, branch `feature/auth`, 23 files indexed,
   > 2 open notes. Ready."

   **DO NOT output a summary or breakdown of the codebase after reading the cache.**
   The one-line confirmation above is sufficient. Only expand beyond it if the user
   explicitly asks for a summary, or if something in the cache is critically unclear
   and you cannot proceed without clarification.

---

## Auto-Update Protocol

Update the cache whenever any of these happen:

| Event | Command |
|-------|---------|
| You write or significantly edit a file | `python scripts/update_cache.py --event write --file <path>` |
| You delete a file | `python scripts/update_cache.py --event delete --file <path>` |
| You rename/move a file | `python scripts/update_cache.py --event rename --file <old> --new-file <new>` |
| A git commit is made | `python scripts/update_cache.py --event git` |
| You learn something worth remembering | `python scripts/update_cache.py --event note --tag <tag> --text "<text>"` |
| Schema drifts badly out of date | `python scripts/update_cache.py --event full` |

If Claude Code hooks are installed, write/edit/delete/rename/commit events fire
automatically — no manual calls needed. See `references/hooks.md` for setup.

Run these **after** the file operation, not before. The update is non-blocking —
if it fails, warn the user but do not halt the main task.

Valid note tags: `#arch` `#todo` `#warn` `#done` `#debt` `#why` `#perf`

---

## Reading the .ctx Format

The `.ctx` schema uses single-character sigils to compress file metadata. You
don't need to memorize it — the format is self-describing — but here's the quick
reference:

```
§F  = file entry       §D = directory (collapsed)    §G = git state
§C  = config files     §X = external deps             §S = types/schemas
§R  = routes           §N = persistent notes
```

Field tokens within `§F` blocks:

```
p:  path        t:  language    sz: line count    ex: exports
im: internal imports            xi: external imports
fn: functions   st: state/classes                 ~:  depends on
!   known issue                 #   inline comment
```

For the full spec (relationship operators, compression rules, §N tag meanings,
`.ctxconfig` options), read: `references/schema.md`

---

## Initializing a New Project

When the user wants to set up ccache on a project:

```bash
# From the project root:
python path/to/ccache/scripts/init_cache.py .

# Or with options:
python scripts/init_cache.py . --output .ctx --config .ctxconfig
```

Then suggest adding to `.gitignore` or committing — both are valid:
- **Commit it**: teammates and CI get instant context on checkout
- **Gitignore it**: keep it local/personal, regenerate as needed

---

## Writing a .ctxconfig

Create `.ctxconfig` at the project root for project-specific behavior:

```json
{
  "include_tests": false,
  "include_dirs": ["src", "lib", "app"],
  "exclude_patterns": ["*.generated.ts", "migrations/"],
  "max_file_lines_for_detail": 500,
  "collapse_unchanged_after_days": 7,
  "auto_update_on": ["file_write", "file_delete", "git_commit"]
}
```

If `include_dirs` is empty, all directories are scanned (respecting
always-skip list: `dist`, `build`, `.next`, `node_modules`, etc.).

---

## IDE / Editor Hook Setup (optional, for fully automatic updates)

For VS Code, add to `.vscode/tasks.json`:

```json
{
  "version": "2.0.0",
  "tasks": [
    {
      "label": "Update ctx cache",
      "type": "shell",
      "command": "python scripts/update_cache.py --event write --file ${file}",
      "runOptions": { "runOn": "folderOpen" }
    }
  ]
}
```

For git hooks, add to `.git/hooks/post-commit`:

```bash
#!/bin/sh
python scripts/update_cache.py --event git
```

---

## Token Budget Guidance

The goal of `.ctx` is to describe an entire project in **under ~950 tokens**.
Keep this in mind when deciding what to cache:

- **Collapse** directories with more than 10 small utility files into one `§D` block
- **Skip** `migrations/`, `fixtures/`, auto-generated files — they pollute signal
- **Truncate** export lists beyond 5 items (the `+N` syntax handles this)
- **Notes (`§N`) are gold** — they carry hard-won context that can't be inferred
  from code structure alone. Encourage the user to add notes after important
  architectural decisions.

If the `.ctx` grows beyond ~150 lines, run `--event full` to re-compact.

---

## Distributing / Publishing

This skill is designed to be published as a standalone GitHub repository.
The recommended repo layout:

```
ccache/
├── SKILL.md
├── README.md          ← user-facing install/usage guide
├── scripts/
│   ├── init_cache.py
│   └── update_cache.py
└── references/
    └── schema.md
```

Users install by cloning and pointing Claude Code's skill path at the directory,
or by running `python scripts/init_cache.py` directly in any project.
