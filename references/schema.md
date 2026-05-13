# .ctx Schema Reference

The `.ctx` format is a compressed project context snapshot designed to minimize token consumption when loading project state into an LLM context window. Every symbol has a defined meaning; whitespace and punctuation are load-bearing.

---

## File Header

Every `.ctx` file begins with a two-line header:

```
@ctx v1 <project_name>
%updated <ISO8601_timestamp>
```

---

## Block Types

Each block opens with a `§` sigil and a single uppercase letter, followed by a colon and the block payload on the same or subsequent lines.

| Sigil | Meaning         | Description                                      |
|-------|-----------------|--------------------------------------------------|
| `§F`  | File            | A source file entry                              |
| `§D`  | Directory       | A directory summary (collapsed subtree)          |
| `§E`  | Entry points    | Top-level exports or public API surface          |
| `§C`  | Config          | Build/environment config files                   |
| `§S`  | Schema/Types    | Type definitions, interfaces, DB schemas         |
| `§R`  | Routes          | HTTP/RPC routes, CLI commands                    |
| `§X`  | External deps   | Third-party dependencies (package.json, etc.)    |
| `§N`  | Notes           | Human or agent-written freeform notes            |
| `§G`  | Git             | Current branch, last commit, dirty files         |

---

## Field Tokens (within §F and §D blocks)

Fields appear inline, space-separated, after the file path.

| Token   | Meaning                        | Example                          |
|---------|--------------------------------|----------------------------------|
| `p`     | Path (relative to root)        | `p src/api/users.ts`             |
| `t`     | File type/language             | `t ts` `t py` `t json`          |
| `sz`    | Approximate size in lines      | `sz 142`                         |
| `ex`    | Exports (comma-separated)      | `ex getUser,createUser,UserType` |
| `im`    | Imports from internal paths    | `im db/client,utils/auth`        |
| `xi`    | Imports from external packages | `xi express,zod`                 |
| `fn`    | Key functions/methods          | `fn handleRequest,validateInput` |
| `st`    | Key state / stores / classes   | `st UserStore,sessionMap`        |
| `~`     | Depends on (other §F paths)    | `~ src/db/client.ts`             |
| `dep`   | Depended on by                 | `dep src/routes/users.ts`        |
| `mod`   | Last modified (ISO date only)  | `mod 2025-05-09`                 |
| `!`     | Flag: file has known issue     | `! missing error handling`       |
| `#`     | Inline comment/note            | `# entry point for auth flow`    |

---

## Relationship Operators

Used in dependency lines and §E blocks.

| Symbol | Meaning                     |
|--------|-----------------------------|
| `~>`   | Calls / invokes             |
| `<~`   | Is called by                |
| `=>`   | Re-exports                  |
| `<>`   | Bidirectional dependency    |
| `--`   | Weak/optional dependency    |

---

## File Importance Tiers

Every file is assigned a tier during `init_cache.py`'s two-pass scan.

### Scoring Formula

```
importance = dep_count + export_count + import_count
```

| Component | Meaning |
|-----------|---------|
| `dep_count` | How many other files import this one (load-bearing?) |
| `export_count` | How much public surface area it exposes |
| `import_count` | How many things it orchestrates or calls |

A file that scores high on all three is a core module. A file scoring zero on all
three is an isolated leaf.

### Tier Assignment

| Tier | Condition | Rendered As |
|------|-----------|-------------|
| **T1** | top `tier1_percentile`% by score **or** entry point filename | Full `§F` block — all fields |
| **T2** | `tier1_percentile`–`tier2_percentile`% band | Compact `§F` block — `ex:` and `dep:` only |
| **T3** | bottom `(100 - tier2_percentile)`% | Bare filename inside a `§D` group block |

Percentiles are computed per-project so thresholds self-calibrate to codebase size.

**Floor guards — T3 never activates when:**
- Total file count < `floor_for_t3` (default 15) — too few files to justify collapsing
- Files in a dir < `floor_dir_for_t3` (default 6) — small dirs always get at least T2

Entry point filenames are always T1 regardless of score:
`index.ts/js`, `main.ts/js/py`, `app.ts/js/py`, `server.ts/js`,
`cli.ts/js/py`, `__init__.py`, `__main__.py`, `routes.ts/js`, `router.ts/js`

Tier cutoffs are configurable in `.ctxconfig` (see below).

### §D Group Block (T2/T3 files)

When a directory contains a mix of T2 and T3 files, they are collapsed into a
single `§D` block. T1 files in the same directory are rendered as full `§F` blocks
above the group.

```
§D src/utils
  token.ts* ex:signJWT,verifyJWT dep:3
  crypto.ts* ex:hashPassword,compareHash
  logger.ts
  constants.ts
  types.ts
```

- Lines ending in `*` are **T2** — filename + inline mini-summary (exports + dep count)
- Plain lines are **T3** — filename + minimum navigation hint:
  - exports if the file has any (capped at 3)
  - else a `#` comment inferred from filename pattern (`# constants`, `# middleware`, etc.)
  - bare filename only if pattern is unknown
- T1 files that ended up grouped are promoted out and rendered separately

## Compression Rules

1. **Omit zero-value fields.** If a file has no exports, omit `ex:`.
2. **Truncate long lists.** More than 5 items in `ex:`, `fn:`, `im:` → keep top 5, append `+N` (e.g. `ex:foo,bar,baz,qux,quux+3`).
3. **Use §D groups for T2/T3.** Mixed directories collapse into one block.
4. **Skip test files by default.** Unless `include_tests: true` is set in `.ctxconfig`, omit `*.test.*`, `*.spec.*`, `__tests__/`.
5. **Skip generated files.** `dist/`, `build/`, `.next/`, `__pycache__/` are always omitted.

---

## §G Block Format

```
§G
branch main
commit a3f9c12 "fix auth token refresh"
dirty src/api/users.ts,src/utils/auth.ts
```

---

## §N Block Format

Agent-written notes persist across sessions. Each note has a timestamp and optional tag.

```
§N
[2025-05-09T14:22Z #arch] Auth uses JWT, refresh tokens stored in Redis, not DB.
[2025-05-09T14:23Z #todo] Migrate users table to new schema before next deploy.
[2025-05-09T14:23Z #warn] Rate limiter is disabled in dev — don't forget to re-enable.
```

Tags: `#arch` `#todo` `#warn` `#done` `#debt` `#why` `#perf`

---

## Full Example

```
@ctx v1 my-api
%updated 2025-05-09T14:30:00Z

§G
branch feature/user-auth
commit b2d11aa "add refresh token endpoint"
dirty src/api/auth.ts

§C
p:package.json xi:express,zod,jsonwebtoken,prisma
p tsconfig.json
p .env.example # see .ctxconfig for secret mapping

§X express@4.18 zod@3.22 jsonwebtoken@9.0 prisma@5.14

§S
p src/types/user.ts t ts sz 34 ex User,UserRole,SessionToken

§R
POST /auth/login ~> src/api/auth.ts:handleLogin
POST /auth/refresh ~> src/api/auth.ts:handleRefresh
GET  /users/:id ~> src/api/users.ts:getUser

§F
p src/api/auth.ts t ts sz 88
  ex handleLogin,handleRefresh
  im src/db/client,src/types/user,src/utils/token
  xi jsonwebtoken,zod
  fn handleLogin,handleRefresh,validateCredentials
  ~ src/db/client.ts,src/utils/token.ts
  # core auth logic; refresh tokens written to Redis via db/client

§F
p src/api/users.ts t ts sz 62
  ex getUser,updateUser
  im src/db/client,src/types/user
  fn getUser,updateUser
  ~ src/db/client.ts
  ! updateUser missing input validation

§F
p src/db/client.ts t ts sz 41
  ex db,redis
  xi prisma,ioredis
  st db,redis
  dep src/api/auth.ts,src/api/users.ts

§D src/utils sz 3
  # token signing, password hashing, logger

§N
[2025-05-09T14:22Z #arch] JWT secret in env:JWT_SECRET. Refresh TTL = 7d.
[2025-05-09T14:25Z #warn] Redis not running in CI — integration tests will skip refresh flow.
[2025-05-09T14:29Z #todo] Add rate limiting to POST /auth/login
```

---

## .ctxconfig

Optional config file at project root. Controls cache behavior.

```json
{
  "include_tests": false,
  "include_dirs": ["src", "lib", "app"],
  "exclude_patterns": ["*.generated.ts", "migrations/"],
  "max_file_lines_for_detail": 500,
  "collapse_unchanged_after_days": 7,
  "auto_update_on": ["file_write", "file_delete", "git_commit"],
  "tier1_percentile": 25,
  "tier2_percentile": 70,
  "floor_for_t3": 15,
  "floor_dir_for_t3": 6
}
```

`tier1_percentile` / `tier2_percentile` — percentile cutoffs. Defaults: top 25% → T1, 25–70% → T2, bottom 30% → T3.

`floor_for_t3` — minimum total file count before any file can drop to T3.

`floor_dir_for_t3` — minimum files in a directory before it collapses to a `§D` group.
Small dirs always render at least T2 inline summaries.
