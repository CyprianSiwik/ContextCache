#!/usr/bin/env python3
"""
install.py — One-shot ccache setup for a project.

Usage:
    python3 /path/to/ContextCache/install.py                 # sets up current directory
    python3 /path/to/ContextCache/install.py /path/to/project

What it does:
    1. Generates .ctx cache
    2. Registers the skill in CLAUDE.md
    3. Adds CLAUDE.md to .gitignore
    4. Installs Claude Code auto-update hooks
"""

import sys
import subprocess
from pathlib import Path


def main():
    cache_root  = Path(__file__).parent.resolve()
    project_dir = Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else Path.cwd()

    if not project_dir.is_dir():
        print(f"ERROR: not a directory: {project_dir}")
        sys.exit(1)

    print(f"Installing ccache for: {project_dir.name}")
    print()

    # ── 1. Generate .ctx ──────────────────────────────────────────────────────
    print("1/4  Generating .ctx cache...")
    result = subprocess.run(
        [sys.executable, str(cache_root / "scripts" / "init_cache.py"), str(project_dir)]
    )
    if result.returncode != 0:
        print("ERROR: cache generation failed — aborting.")
        sys.exit(1)

    # ── 2. Register skill in CLAUDE.md ────────────────────────────────────────
    print("2/4  Registering skill in CLAUDE.md...")
    skill_path = cache_root / "SKILL.md"
    skill_line = f"@{skill_path}\n"
    claude_md  = project_dir / "CLAUDE.md"

    if claude_md.exists():
        existing = claude_md.read_text(encoding="utf-8")
        if str(skill_path) in existing:
            print("     Already registered — skipping.")
        else:
            claude_md.write_text(existing.rstrip() + "\n" + skill_line, encoding="utf-8")
            print(f"     Added to {claude_md}")
    else:
        claude_md.write_text(skill_line, encoding="utf-8")
        print(f"     Created {claude_md}")

    # ── 3. Gitignore CLAUDE.md ────────────────────────────────────────────────
    print("3/4  Adding CLAUDE.md to .gitignore...")
    gitignore = project_dir / ".gitignore"

    if gitignore.exists():
        content = gitignore.read_text(encoding="utf-8")
        if "CLAUDE.md" in content:
            print("     Already in .gitignore — skipping.")
        else:
            gitignore.write_text(content.rstrip() + "\nCLAUDE.md\n", encoding="utf-8")
            print("     Done.")
    else:
        gitignore.write_text("CLAUDE.md\n", encoding="utf-8")
        print("     Created .gitignore.")

    # ── 4. Install hooks ──────────────────────────────────────────────────────
    print("4/4  Installing Claude Code hooks...")
    result = subprocess.run(
        [sys.executable, str(cache_root / "scripts" / "install_hooks.py"),
         "--project-dir", str(project_dir)]
    )
    if result.returncode != 0:
        print("     WARNING: hook install failed. Run scripts/install_hooks.py manually.")

    # ── Done ──────────────────────────────────────────────────────────────────
    print()
    print(f"✓ ccache is ready.")
    print(f"  .ctx           — project snapshot ({project_dir / '.ctx'})")
    print(f"  CLAUDE.md      — skill registered (gitignored)")
    print(f"  hooks          — auto-update on write/edit/delete/commit")
    print()
    print("Use /ccache to orient Claude around this project.")
    print("To update manually: python3 scripts/update_cache.py --event full")


if __name__ == "__main__":
    main()
