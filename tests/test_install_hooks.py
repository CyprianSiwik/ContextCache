"""Regression test for the install_hooks.py bug where installing hooks for
a second project silently deleted the first project's hook entries.

is_ctx_matcher() used to match purely on the hook script's path, which is
identical across every project (it's the same physical ctx_hook.sh). That
made the "remove existing ctxc matchers before reinstalling" step in
install() remove *every* project's entries, not just the one being
(re)installed.
"""
import json

import install_hooks


def _patch_settings_path(monkeypatch, tmp_path):
    settings_path = tmp_path / "settings.json"
    monkeypatch.setattr(install_hooks, "get_settings_path", lambda: settings_path)
    return settings_path


def _matcher_project_dirs(settings: dict) -> set:
    dirs = set()
    for matcher in settings.get("hooks", {}).get("PostToolUse", []):
        for hook in matcher.get("hooks", []):
            cmd = hook.get("command", "")
            # CLAUDE_PROJECT_DIR="<dir>" bash "<script>"
            start = cmd.find('CLAUDE_PROJECT_DIR="') + len('CLAUDE_PROJECT_DIR="')
            end = cmd.find('"', start)
            dirs.add(cmd[start:end])
    return dirs


def test_installing_second_project_preserves_first_projects_hooks(tmp_path, monkeypatch):
    settings_path = _patch_settings_path(monkeypatch, tmp_path)
    proj_a = tmp_path / "proj_a"
    proj_b = tmp_path / "proj_b"
    proj_a.mkdir()
    proj_b.mkdir()

    install_hooks.install(proj_a)
    install_hooks.install(proj_b)

    settings = json.loads(settings_path.read_text())
    dirs = _matcher_project_dirs(settings)
    assert str(proj_a) in dirs, "installing project B wiped project A's hooks"
    assert str(proj_b) in dirs


def test_reinstalling_same_project_replaces_rather_than_duplicates(tmp_path, monkeypatch):
    settings_path = _patch_settings_path(monkeypatch, tmp_path)
    proj_a = tmp_path / "proj_a"
    proj_a.mkdir()

    install_hooks.install(proj_a)
    install_hooks.install(proj_a)

    settings = json.loads(settings_path.read_text())
    matchers = settings["hooks"]["PostToolUse"]
    assert len(matchers) == 3, "reinstalling the same project should replace, not duplicate, its 3 matchers"


def test_uninstall_removes_hooks_across_all_projects(tmp_path, monkeypatch):
    settings_path = _patch_settings_path(monkeypatch, tmp_path)
    proj_a = tmp_path / "proj_a"
    proj_b = tmp_path / "proj_b"
    proj_a.mkdir()
    proj_b.mkdir()

    install_hooks.install(proj_a)
    install_hooks.install(proj_b)
    install_hooks.uninstall()

    settings = json.loads(settings_path.read_text())
    assert settings["hooks"]["PostToolUse"] == []
