---
name: context_cache
description: >
  Persistent, compressed project context cache. Use this skill whenever starting
  a new session in a project, whenever the user says "update the cache", "refresh
  context", "init cache", or "what does the cache say". Also triggers when the
  user asks Claude to remember something about the project architecture, mark a
  todo, or leave a note for next session. Use after any file creation, deletion,
  or rename to keep the cache current. If a .ctx file exists in the project root
  or any parent directory, always read it at session start before doing anything
  else — it is the authoritative project snapshot and replaces the need to re-scan
  all files from scratch.
---

# context_cache

A token-efficient, self-updating project context system. One `.ctx` file at the
project root gives Claude everything it needs to reorient on session start without
re-reading the entire codebase.

## How It Works

- **`.ctx`** — compressed project snapshot (custom shorthand format; see schema below)
- **`.ctxconfig`** — optional config (what to include/exclude, auto-update triggers)
- **`scripts/init_cache.py`** — generate the initial cache from scratch
- **`scripts/update_cache.py`** — patch the cache on individual file events
- **`references/schema.md`** — full format spec (load this when you need to hand-write or debug a `.ctx` block)

---

## Session Start Protocol

**Every session, before doing anything else:**

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

When the user wants to set up context_cache on a project:

```bash
# From the project root:
python path/to/context_cache/scripts/init_cache.py .

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

The goal of `.ctx` is to describe an entire project in **under ~800 tokens**.
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
context_cache/
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
