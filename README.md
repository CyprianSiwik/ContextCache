# context_cache

> A token-efficient, self-updating project context system for Claude agents.

Stop burning tokens every session reacclimating Claude to your codebase. `context_cache` maintains a compressed `.ctx` snapshot of your project that Claude reads in seconds at session start — instead of re-reading dozens of files.

---

## The Problem

Every time you spin up a Claude agent on a large project, it has to rediscover everything: file structure, what exports what, where the entry points are, what architectural decisions were made. That's a lot of tokens burned before any real work happens.

## The Solution

A single `.ctx` file at your project root. It uses a compact shorthand format to encode your entire project's structure — file tree, exports, imports, dependencies, git state, and persistent notes — in under 800 tokens. Claude reads it once at session start and immediately knows where everything is.

The cache updates itself automatically as you work. Add a file? Cache updates. Delete one? Cache updates. Learn something important about the architecture? Leave a note in the cache for next session.

---

## Quick Start

```bash
# Clone once, anywhere on your machine
git clone https://github.com/CyprianSiwik/ContextCache

# Run the installer from your project root
cd your-project
python3 /path/to/ContextCache/install.py
```

That's it. The installer:
- generates the `.ctx` snapshot
- registers the skill in `CLAUDE.md`
- adds `CLAUDE.md` to `.gitignore` (the path is machine-specific)
- installs Claude Code hooks for auto-updates

Next time you open Claude in this project it reads the cache automatically.

---

## What a .ctx Looks Like

```
@ctx v1 my-api
%updated 2025-05-09T14:30:00Z

§G
branch feature/user-auth
commit b2d11aa "add refresh token endpoint"
dirty src/api/auth.ts

§X express@4.18 zod@3.22 jsonwebtoken@9.0 prisma@5.14

§F
p src/api/auth.ts t ts sz 88
  ex handleLogin,handleRefresh
  im db/client,types/user,utils/token
  xi jsonwebtoken,zod
  fn handleLogin,handleRefresh,validateCredentials

§F
p src/db/client.ts t ts sz 41
  ex db,redis
  xi prisma,ioredis
  st db,redis
  dep src/api/auth.ts,src/api/users.ts

§N
[2025-05-09T14:22Z #arch] JWT secret in env:JWT_SECRET. Refresh TTL = 7d.
[2025-05-09T14:25Z #warn] Redis not running in CI — integration tests skip refresh.
[2025-05-09T14:29Z #todo] Add rate limiting to POST /auth/login
```

Human-readable, diff-friendly, ~120 tokens for this example.

---

## Format Reference

See [`references/schema.md`](references/schema.md) for the full spec. Quick version:

| Sigil | Meaning        |
|-------|----------------|
| `§F`  | File entry     |
| `§D`  | Directory (collapsed subtree) |
| `§G`  | Git state      |
| `§C`  | Config files   |
| `§X`  | External deps  |
| `§S`  | Types/schemas  |
| `§R`  | Routes         |
| `§N`  | Persistent notes |

Field tokens: `p`  path · `t`  language · `sz` lines · `ex` exports · `im` internal imports · `xi` external imports · `fn` functions · `st` state/classes · `~`  depends on · `!`  issue flag · `#`  comment

---

## Keeping the Cache Updated

### Automatic — Claude Code Hooks (recommended)

Install once, updates forever. Hooks fire on every write, edit, delete, rename, and commit.

```bash
# From your project root (after init_cache.py)
python path/to/context_cache/scripts/install_hooks.py --project-dir .

# To uninstall
python scripts/install_hooks.py --uninstall
```

See [`references/hooks.md`](references/hooks.md) for full details and multi-project setup.

### Manual

```bash
python scripts/update_cache.py --event write  --file src/api/users.ts
python scripts/update_cache.py --event delete --file src/api/old.ts
python scripts/update_cache.py --event rename --file src/old.ts --new-file src/new.ts
python scripts/update_cache.py --event git
python scripts/update_cache.py --event note --tag arch --text "Auth uses JWT"
python scripts/update_cache.py --event full   # full re-scan
```

### Git Hook

Add to `.git/hooks/post-commit` (`chmod +x`):

```bash
#!/bin/sh
python scripts/update_cache.py --event git
```

### VS Code

Add to `.vscode/tasks.json`:

```json
{
  "version": "2.0.0",
  "tasks": [{
    "label": "Update ctx on save",
    "type": "shell",
    "command": "python scripts/update_cache.py --event write --file ${file}"
  }]
}
```

---

## Configuration

Create `.ctxconfig` at your project root:

```json
{
  "include_tests": false,
  "include_dirs": ["src", "lib"],
  "exclude_patterns": ["*.generated.ts", "migrations/"],
  "max_file_lines_for_detail": 500,
  "collapse_unchanged_after_days": 7,
  "auto_update_on": ["file_write", "file_delete", "git_commit"]
}
```

All fields are optional. Without a config, the scanner uses sensible defaults and skips `dist/`, `build/`, `node_modules/`, `.next/`, `__pycache__/`, etc.

---

## Using as a Claude Skill

After cloning, register the skill in your project's `CLAUDE.md`:

```bash
# From your project root:
echo "@/path/to/ContextCache/SKILL.md" >> CLAUDE.md
```

Replace `/path/to/ContextCache` with wherever you cloned this repo. For example:

```
@/Users/yourname/tools/ContextCache/SKILL.md
```

Then add `CLAUDE.md` to your `.gitignore` — the path is machine-specific and will break for collaborators:

```
echo "CLAUDE.md" >> .gitignore
```

Once registered, Claude will automatically read `.ctx` at session start, update it after file operations, and add notes when it learns something worth preserving. Each teammate registers their own local path.

---

## Note Tags

Use these in `§N` blocks for structured searchability:

| Tag     | Meaning                                  |
|---------|------------------------------------------|
| `#arch` | Architectural decision or pattern        |
| `#todo` | Something that needs doing               |
| `#warn` | Watch out — subtle gotcha or footgun     |
| `#done` | Completed task (safe to clean up)        |
| `#debt` | Technical debt acknowledged              |
| `#why`  | Explains a non-obvious decision          |
| `#perf` | Performance note or constraint           |

---

## Token Budget

Target: describe your whole project in under **950 tokens**.

- Collapse unchanged dirs with `§D` blocks
- Skip `migrations/`, fixtures, generated files
- Truncate long export lists (the `+N` syntax: `ex:foo,bar,baz+12`)
- Notes (`§N`) are the highest-value entries — they carry knowledge that can't be inferred from code

If `.ctx` exceeds ~150 lines, run `--event full` to recompact.

---

## Language Support

Fully analyzed (exports, imports, functions, types):

- TypeScript / TSX
- JavaScript / JSX
- Python
- Swift
- Go
- Kotlin
- Java
- Ruby
- Rust
- C / C++ / H

Other languages are scanned for line count and path only.

---

## .gitignore or Commit?

Both are valid:

- **Commit `.ctx`**: teammates and CI get instant context on checkout. Good for stable shared projects.
- **Gitignore `.ctx`**: keep it personal/local. Regenerate per-machine. Better when the cache would create merge conflicts.

Suggested `.gitignore` entry if going local-only:
```
.ctx
.ctxconfig
```

---

## Requirements

- Python 3.8+
- No external dependencies (stdlib only)
- Git optional (used for `§G` blocks only)

---

## License

MIT
