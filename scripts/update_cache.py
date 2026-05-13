#!/usr/bin/env python3
"""
update_cache.py — Incrementally update a .ctx file when source files change.

Usage:
    python update_cache.py --event write  --file src/api/users.ts
    python update_cache.py --event delete --file src/api/old.ts
    python update_cache.py --event rename --file src/old.ts --new-file src/new.ts
    python update_cache.py --event note   --tag arch --text "JWT stored in Redis"
    python update_cache.py --event full   # Re-run full init (nuclear option)
    python update_cache.py --event git    # Refresh §G block from current git state

Options:
    --ctx       Path to .ctx file (default: .ctx in cwd or nearest parent)
    --root      Project root (default: directory containing .ctx)
    --dry-run   Print what would change without writing
"""

import re
import sys
import os
import argparse
import subprocess
from pathlib import Path
from datetime import datetime, timezone

# ── Locate .ctx ───────────────────────────────────────────────────────────────

def find_ctx_file(start: Path):
    current = start.resolve()
    for _ in range(10):
        candidate = current / ".ctx"
        if candidate.exists():
            return candidate
        parent = current.parent
        if parent == current:
            break
        current = parent
    return None

# ── Timestamp ─────────────────────────────────────────────────────────────────

def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

def update_timestamp(content: str) -> str:
    return re.sub(r"%updated .*", f"%updated {now_iso()}", content)

# ── §F block parser/replacer ──────────────────────────────────────────────────

def extract_file_block(content: str, rel_path: str) -> tuple:
    """
    Returns (start_idx, end_idx) of the §F block for rel_path, or (-1, -1).
    A block starts at `§F\np:<rel_path>` and ends just before the next `§` sigil
    or end of string.
    """
    escaped = re.escape(rel_path)
    pattern = re.compile(rf"§F\np {escaped}[^\n]*(?:\n  [^\n]*)*", re.MULTILINE)
    m = pattern.search(content)
    if not m:
        return -1, -1
    return m.start(), m.end()

def remove_file_block(content: str, rel_path: str) -> str:
    start, end = extract_file_block(content, rel_path)
    if start == -1:
        return content
    # Remove the block and the surrounding blank line
    snippet = content[start:end]
    content = content[:start] + content[end:]
    # Clean up double blank lines
    content = re.sub(r"\n{3,}", "\n\n", content)
    return content

def remove_from_dir_block(content: str, rel_path: str) -> str:
    """Remove a file's entry from its §D group block, if present."""
    parts = rel_path.rsplit("/", 1)
    dir_path = parts[0] if len(parts) == 2 else "."
    filename = parts[-1]

    escaped_dir  = re.escape(dir_path)
    escaped_file = re.escape(filename)

    d_pattern = re.compile(rf"§D {escaped_dir}\n((?:  [^\n]*\n)*)", re.MULTILINE)
    m = d_pattern.search(content)
    if not m:
        return content

    new_lines = re.sub(rf"  {escaped_file}[^\n]*\n", "", m.group(1))

    if not new_lines.strip():
        content = content[:m.start()] + content[m.end():]
        content = re.sub(r"\n{3,}", "\n\n", content)
    else:
        content = content[:m.start()] + f"§D {dir_path}\n{new_lines}" + content[m.end():]

    return content

def replace_or_insert_file_block(content: str, new_block: str, rel_path: str) -> str:
    start, end = extract_file_block(content, rel_path)
    if start != -1:
        return content[:start] + new_block + content[end:]
    else:
        # Insert before §N block if present, else append
        n_idx = content.find("\n§N")
        if n_idx != -1:
            return content[:n_idx] + "\n\n" + new_block + content[n_idx:]
        return content.rstrip() + "\n\n" + new_block + "\n"

# ── §G block updater ──────────────────────────────────────────────────────────

def refresh_git_block(content: str, root: Path) -> str:
    try:
        branch = subprocess.check_output(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            cwd=root, stderr=subprocess.DEVNULL
        ).decode().strip()
        commit_hash = subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=root, stderr=subprocess.DEVNULL
        ).decode().strip()
        commit_msg = subprocess.check_output(
            ["git", "log", "-1", "--pretty=%s"],
            cwd=root, stderr=subprocess.DEVNULL
        ).decode().strip()
        dirty_raw = subprocess.check_output(
            ["git", "diff", "--name-only"],
            cwd=root, stderr=subprocess.DEVNULL
        ).decode().strip()
        dirty = [f for f in dirty_raw.splitlines() if f]

        new_block = f"§G\nbranch {branch}\ncommit {commit_hash} \"{commit_msg}\""
        if dirty:
            new_block += f"\ndirty {','.join(dirty[:10])}"

        # Replace existing §G block
        g_pattern = re.compile(r"§G\n(?:.*\n)*?(?=\n§|\Z)", re.MULTILINE)
        m = g_pattern.search(content)
        if m:
            return content[:m.start()] + new_block + "\n" + content[m.end():]
        else:
            # Insert after header
            header_end = content.find("\n\n")
            if header_end != -1:
                return content[:header_end] + "\n\n" + new_block + content[header_end:]
        return content
    except Exception:
        return content

# ── §N note appender ──────────────────────────────────────────────────────────

def append_note(content: str, tag: str, text: str) -> str:
    ts = now_iso()
    note_line = f"[{ts} #{tag}] {text}"

    n_idx = content.find("§N")
    if n_idx == -1:
        return content.rstrip() + f"\n\n§N\n{note_line}\n"

    # Find end of §N block
    block_start = n_idx
    after = content[block_start + 2:]  # skip '§N'
    # Insert before next §-block or end
    next_sigil = re.search(r"\n§[A-Z]", after)
    if next_sigil:
        insert_at = block_start + 2 + next_sigil.start()
        return content[:insert_at] + f"\n{note_line}" + content[insert_at:]
    else:
        return content.rstrip() + f"\n{note_line}\n"

# ── File block generator (mirrors init_cache logic) ──────────────────────────

def build_updated_file_block(root: Path, rel_path: str, ctx_content: str = "") -> str:
    """
    Re-analyze a single file and produce its tiered §F block.
    Performs a lightweight rescore using the existing .ctx dep data when available,
    otherwise falls back to scoring the file in isolation.
    """
    sys.path.insert(0, str(Path(__file__).parent))
    from init_cache import (
        SOURCE_EXTENSIONS, analyze_file, count_lines,
        build_tier1_block, build_tier2_block,
        score_file, assign_tiers, load_config,
        scan_project, build_dep_graph,
    )

    fpath = root / rel_path
    if not fpath.exists():
        return ""

    suffix = fpath.suffix.lower()
    lang = SOURCE_EXTENSIONS.get(suffix, "txt")

    # Full rescan to get accurate dep graph and percentile thresholds
    cfg = load_config(root)
    files = scan_project(root, cfg)
    dep_counts = build_dep_graph(files)

    # Ensure the written file is represented even if new
    if rel_path not in files:
        analysis = analyze_file(fpath, lang)
        files[rel_path] = {
            "path": fpath,
            "lang": lang,
            "analysis": analysis,
            "line_count": count_lines(fpath),
        }

    # Score all files so percentile thresholds are accurate
    scored = assign_tiers(files, dep_counts, cfg)
    data, score, tier = scored.get(rel_path, (files[rel_path], 0, 2))

    if tier == 1:
        return build_tier1_block(rel_path, data, dep_counts)
    elif tier == 2:
        return build_tier2_block(rel_path, data, dep_counts)
    else:
        # T3 — minimal block so the file remains findable in the cache
        lc = data["line_count"]
        return f"§F\np {rel_path} t {lang} sz {lc}"

# ── Event handlers ─────────────────────────────────────────────────────────────

def handle_write(content: str, root: Path, rel_path: str) -> str:
    content = remove_from_dir_block(content, rel_path)
    new_block = build_updated_file_block(root, rel_path, ctx_content=content)
    if not new_block:
        return content
    return replace_or_insert_file_block(content, new_block, rel_path)

def handle_delete(content: str, rel_path: str) -> str:
    content = remove_file_block(content, rel_path)
    return remove_from_dir_block(content, rel_path)

def handle_rename(content: str, root: Path, old_path: str, new_path: str) -> str:
    content = remove_file_block(content, old_path)
    content = remove_from_dir_block(content, old_path)
    new_block = build_updated_file_block(root, new_path, ctx_content=content)
    if new_block:
        content = replace_or_insert_file_block(content, new_block, new_path)
    return content

# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Incrementally update a .ctx file.")
    parser.add_argument("--event", required=True,
                        choices=["write", "delete", "rename", "note", "git", "full"],
                        help="Type of change event")
    parser.add_argument("--file", help="Relative or absolute path to the changed file")
    parser.add_argument("--new-file", help="New path (for rename events)")
    parser.add_argument("--tag", default="note", help="Note tag (for note events)")
    parser.add_argument("--text", help="Note text (for note events)")
    parser.add_argument("--ctx", help="Path to .ctx file (default: auto-detect)")
    parser.add_argument("--root", help="Project root directory")
    parser.add_argument("--dry-run", action="store_true", help="Print changes without writing")
    args = parser.parse_args()

    # Locate .ctx
    cwd = Path.cwd()
    ctx_path = Path(args.ctx) if args.ctx else find_ctx_file(cwd)
    if not ctx_path:
        print("ERROR: No .ctx file found. Run init_cache.py first.", file=sys.stderr)
        sys.exit(1)

    root = Path(args.root).resolve() if args.root else ctx_path.parent

    # Handle full re-init
    if args.event == "full":
        print("Running full re-init via init_cache.py ...")
        sys.path.insert(0, str(Path(__file__).parent))
        from init_cache import load_config, generate_ctx
        cfg = load_config(root)
        generate_ctx(root, ctx_path, cfg)
        print(f"✓ Full re-init complete: {ctx_path}")
        return

    content = ctx_path.read_text(encoding="utf-8")

    # Resolve relative file path
    def to_rel(path_arg: str) -> str:
        p = Path(path_arg)
        if p.is_absolute():
            try:
                return str(p.relative_to(root)).replace("\\", "/")
            except ValueError:
                return path_arg
        return str(p).replace("\\", "/")

    if args.event == "write":
        if not args.file:
            print("ERROR: --file required for write event", file=sys.stderr)
            sys.exit(1)
        rel = to_rel(args.file)
        content = handle_write(content, root, rel)
        print(f"Updated §F block for {rel}")

    elif args.event == "delete":
        if not args.file:
            print("ERROR: --file required for delete event", file=sys.stderr)
            sys.exit(1)
        rel = to_rel(args.file)
        content = handle_delete(content, rel)
        print(f"Removed §F block for {rel}")

    elif args.event == "rename":
        if not args.file or not args.new_file:
            print("ERROR: --file and --new-file required for rename event", file=sys.stderr)
            sys.exit(1)
        old_rel = to_rel(args.file)
        new_rel = to_rel(args.new_file)
        content = handle_rename(content, root, old_rel, new_rel)
        print(f"Renamed {old_rel} → {new_rel} in cache")

    elif args.event == "git":
        content = refresh_git_block(content, root)
        print("Refreshed §G git block")

    elif args.event == "note":
        if not args.text:
            print("ERROR: --text required for note event", file=sys.stderr)
            sys.exit(1)
        content = append_note(content, args.tag, args.text)
        print(f"Appended note [{args.tag}]: {args.text[:60]}")

    content = update_timestamp(content)

    if args.dry_run:
        print("\n── DRY RUN ── resulting .ctx:\n")
        print(content)
    else:
        ctx_path.write_text(content, encoding="utf-8")
        print(f"✓ {ctx_path} updated")

if __name__ == "__main__":
    main()
