"""End-to-end tests that run init_cache.py / update_cache.py as real
subprocesses against a throwaway git repo, the way a user (or the Claude
Code hook) actually invokes them.
"""
import re

from conftest import run_script, write_file


def strip_timestamp(ctx_text: str) -> str:
    return re.sub(r"%updated .*", "%updated <ts>", ctx_text)


def test_init_cache_creates_ctx_file(git_repo):
    write_file(git_repo, "src/main.py", "def main():\n    pass\n")
    result = run_script("init_cache.py", [str(git_repo)], cwd=git_repo)
    assert result.returncode == 0, result.stderr
    ctx = git_repo / ".ctx"
    assert ctx.exists()
    content = ctx.read_text()
    assert "src/main.py" in content
    assert "main" in content


def test_write_event_updates_existing_block(git_repo):
    write_file(git_repo, "src/main.py", "def main():\n    pass\n")
    run_script("init_cache.py", [str(git_repo)], cwd=git_repo)

    write_file(git_repo, "src/main.py", "def main():\n    pass\n\ndef helper():\n    pass\n")
    result = run_script(
        "update_cache.py", ["--event", "write", "--file", "src/main.py"], cwd=git_repo
    )
    assert result.returncode == 0, result.stderr
    content = (git_repo / ".ctx").read_text()
    assert "helper" in content


def test_delete_event_removes_block(git_repo):
    write_file(git_repo, "src/main.py", "def main():\n    pass\n")
    run_script("init_cache.py", [str(git_repo)], cwd=git_repo)

    (git_repo / "src" / "main.py").unlink()
    result = run_script("update_cache.py", ["--event", "delete", "--file", "src/main.py"], cwd=git_repo)
    assert result.returncode == 0, result.stderr
    content = (git_repo / ".ctx").read_text()
    assert "src/main.py" not in content


def test_incremental_write_converges_with_full_rescan(git_repo):
    """Writing a new file via --event write should produce the same §F
    entry that a full init_cache.py rescan would have produced for it —
    i.e. incremental updates shouldn't drift from what a from-scratch scan
    considers correct."""
    write_file(git_repo, "src/main.py", "def main():\n    pass\n")
    run_script("init_cache.py", [str(git_repo)], cwd=git_repo)

    write_file(git_repo, "src/new_module.py", "def new_fn():\n    return 1\n")
    run_script(
        "update_cache.py", ["--event", "write", "--file", "src/new_module.py"], cwd=git_repo
    )
    incremental_ctx = strip_timestamp((git_repo / ".ctx").read_text())

    # Nuke the cache and do a from-scratch scan of the same tree for comparison.
    (git_repo / ".ctx").unlink()
    run_script("init_cache.py", [str(git_repo)], cwd=git_repo)
    full_rescan_ctx = strip_timestamp((git_repo / ".ctx").read_text())

    def file_block(ctx_text, path):
        m = re.search(rf"§F\np {re.escape(path)}(?=\s).*?(?=\n\n|\n§|\Z)", ctx_text, re.DOTALL)
        assert m, f"{path} not found in:\n{ctx_text}"
        return m.group(0)

    assert file_block(incremental_ctx, "src/new_module.py") == file_block(full_rescan_ctx, "src/new_module.py")


def test_rename_event_moves_block(git_repo):
    write_file(git_repo, "src/old_name.py", "def fn():\n    pass\n")
    run_script("init_cache.py", [str(git_repo)], cwd=git_repo)

    (git_repo / "src" / "old_name.py").rename(git_repo / "src" / "new_name.py")
    result = run_script(
        "update_cache.py",
        ["--event", "rename", "--file", "src/old_name.py", "--new-file", "src/new_name.py"],
        cwd=git_repo,
    )
    assert result.returncode == 0, result.stderr
    content = (git_repo / ".ctx").read_text()
    assert "src/old_name.py" not in content
    assert "src/new_name.py" in content
