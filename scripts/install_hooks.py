#!/usr/bin/env python3
"""
install_hooks.py — Install context_cache hooks into ~/.claude/settings.json

Usage:
    python scripts/install_hooks.py [--project-dir /path/to/project]
    python scripts/install_hooks.py --uninstall

This adds PostToolUse hooks to Claude Code that automatically update .ctx
when files are created, edited, deleted, renamed, or committed.

Safe to run multiple times — checks for existing entries before adding.
"""

import json
import os
import sys
import argparse
import shutil
from pathlib import Path

HOOK_ID = "context_cache"

def get_settings_path() -> Path:
    return Path.home() / ".claude" / "settings.json"

def load_settings(path: Path) -> dict:
    if path.exists():
        try:
            return json.loads(path.read_text())
        except Exception:
            print(f"Warning: could not parse {path}, starting fresh.")
    return {}

def save_settings(path: Path, settings: dict):
    path.parent.mkdir(parents=True, exist_ok=True)
    # Backup first
    if path.exists():
        shutil.copy(path, path.with_suffix(".json.bak"))
    path.write_text(json.dumps(settings, indent=2))

def build_hook_entries(hook_script: Path, project_dir: Path) -> list:
    """
    Build the hook entries for Claude Code's settings.json.
    Each entry runs ctx_hook.sh with the right env vars set.
    """
    hook_cmd = (
        f'CLAUDE_TOOL_NAME="$CLAUDE_TOOL_NAME" '
        f'CLAUDE_TOOL_INPUT="$CLAUDE_TOOL_INPUT" '
        f'CLAUDE_PROJECT_DIR="{project_dir}" '
        f'bash "{hook_script}"'
    )

    return [
        {
            "id": f"{HOOK_ID}_write",
            "description": "context_cache: update .ctx on file write/edit",
            "event": "PostToolUse",
            "tool": "Write",
            "command": hook_cmd,
        },
        {
            "id": f"{HOOK_ID}_edit",
            "description": "context_cache: update .ctx on file edit",
            "event": "PostToolUse",
            "tool": "Edit",
            "command": hook_cmd,
        },
        {
            "id": f"{HOOK_ID}_bash",
            "description": "context_cache: update .ctx on rm/mv/git commit",
            "event": "PostToolUse",
            "tool": "Bash",
            "command": hook_cmd,
        },
    ]

def install(project_dir: Path):
    settings_path = get_settings_path()
    hook_script   = (Path(__file__).parent.parent / "hooks" / "ctx_hook.sh").resolve()

    if not hook_script.exists():
        print(f"ERROR: hook script not found at {hook_script}")
        sys.exit(1)

    settings = load_settings(settings_path)
    hooks    = settings.setdefault("hooks", [])

    # Remove any existing context_cache hooks (clean reinstall)
    existing_ids = {f"{HOOK_ID}_write", f"{HOOK_ID}_edit", f"{HOOK_ID}_bash"}
    hooks[:] = [h for h in hooks if h.get("id") not in existing_ids]

    # Add new entries
    new_entries = build_hook_entries(hook_script, project_dir)
    hooks.extend(new_entries)
    settings["hooks"] = hooks

    save_settings(settings_path, settings)
    print(f"✓ Installed context_cache hooks into {settings_path}")
    print(f"  Project dir : {project_dir}")
    print(f"  Hook script : {hook_script}")
    print(f"  Hooks added : {', '.join(e['tool'] for e in new_entries)}")
    print(f"  Backup saved: {settings_path.with_suffix('.json.bak')}")
    print()
    print("  Hooks will fire automatically on:")
    print("    Write / Edit tool  → --event write")
    print("    Bash rm            → --event delete")
    print("    Bash mv            → --event rename")
    print("    Bash git commit    → --event git")
    print()
    print("  To uninstall: python scripts/install_hooks.py --uninstall")

def uninstall():
    settings_path = get_settings_path()
    settings = load_settings(settings_path)
    hooks = settings.get("hooks", [])

    existing_ids = {f"{HOOK_ID}_write", f"{HOOK_ID}_edit", f"{HOOK_ID}_bash"}
    before = len(hooks)
    hooks[:] = [h for h in hooks if h.get("id") not in existing_ids]
    removed = before - len(hooks)

    if removed == 0:
        print("No context_cache hooks found — nothing to uninstall.")
        return

    settings["hooks"] = hooks
    save_settings(settings_path, settings)
    print(f"✓ Removed {removed} context_cache hook(s) from {settings_path}")

def main():
    parser = argparse.ArgumentParser(description="Install context_cache hooks into Claude Code.")
    parser.add_argument(
        "--project-dir",
        default=".",
        help="Project root directory (default: current directory)"
    )
    parser.add_argument(
        "--uninstall",
        action="store_true",
        help="Remove context_cache hooks from settings.json"
    )
    args = parser.parse_args()

    if args.uninstall:
        uninstall()
    else:
        project_dir = Path(args.project_dir).resolve()
        if not (project_dir / ".ctx").exists():
            print(f"Warning: no .ctx file found in {project_dir}")
            print("  Run init_cache.py first, or hooks will silently no-op.")
            print()
        install(project_dir)

if __name__ == "__main__":
    main()
