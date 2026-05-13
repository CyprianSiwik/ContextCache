#!/usr/bin/env python3
"""
install_hooks.py — Install context_cache hooks into ~/.claude/settings.json

Usage:
    python scripts/install_hooks.py [--project-dir /path/to/project]
    python scripts/install_hooks.py --uninstall

This adds PostToolUse hooks to Claude Code that automatically update .ctx
when files are created, edited, deleted, renamed, or committed.

Safe to run multiple times — re-running replaces existing entries.
"""

import json
import os
import sys
import argparse
import shutil
from pathlib import Path

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
    if path.exists():
        shutil.copy(path, path.with_suffix(".json.bak"))
    path.write_text(json.dumps(settings, indent=2))

def is_ctx_matcher(matcher: dict, hook_script: Path) -> bool:
    script_str = str(hook_script)
    return any(script_str in h.get("command", "") for h in matcher.get("hooks", []))

def build_hook_matchers(hook_script: Path, project_dir: Path) -> list:
    """
    Build PostToolUse matcher entries for Claude Code's settings.json hooks object.
    Format: hooks.PostToolUse = [ { matcher, hooks: [{type, command}] }, ... ]
    """
    hook_cmd = f'CLAUDE_PROJECT_DIR="{project_dir}" bash "{hook_script}"'

    return [
        {"matcher": "Write", "hooks": [{"type": "command", "command": hook_cmd}]},
        {"matcher": "Edit",  "hooks": [{"type": "command", "command": hook_cmd}]},
        {"matcher": "Bash",  "hooks": [{"type": "command", "command": hook_cmd}]},
    ]

def install(project_dir: Path):
    settings_path = get_settings_path()
    hook_script   = (Path(__file__).parent.parent / "hooks" / "ctx_hook.sh").resolve()

    if not hook_script.exists():
        print(f"ERROR: hook script not found at {hook_script}")
        sys.exit(1)

    settings   = load_settings(settings_path)
    hooks_obj  = settings.setdefault("hooks", {})
    # Migrate from old array format if needed
    if isinstance(hooks_obj, list):
        hooks_obj = {}
    post_tool  = hooks_obj.setdefault("PostToolUse", [])

    # Remove existing context_cache matchers for this project (clean reinstall)
    post_tool[:] = [m for m in post_tool if not is_ctx_matcher(m, hook_script)]

    new_matchers = build_hook_matchers(hook_script, project_dir)
    post_tool.extend(new_matchers)
    hooks_obj["PostToolUse"] = post_tool
    settings["hooks"] = hooks_obj

    save_settings(settings_path, settings)
    print(f"✓ Installed context_cache hooks into {settings_path}")
    print(f"  Project dir : {project_dir}")
    print(f"  Hook script : {hook_script}")
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
    hook_script   = (Path(__file__).parent.parent / "hooks" / "ctx_hook.sh").resolve()
    settings      = load_settings(settings_path)
    hooks_obj     = settings.get("hooks", {})

    if isinstance(hooks_obj, list):
        print("No context_cache hooks found — nothing to uninstall.")
        return

    post_tool = hooks_obj.get("PostToolUse", [])
    before    = len(post_tool)
    post_tool[:] = [m for m in post_tool if not is_ctx_matcher(m, hook_script)]
    removed   = before - len(post_tool)

    if removed == 0:
        print("No context_cache hooks found — nothing to uninstall.")
        return

    hooks_obj["PostToolUse"] = post_tool
    settings["hooks"] = hooks_obj
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
