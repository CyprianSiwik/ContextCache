"""Tests for should_skip() in scripts/init_cache.py.

should_skip() decides whether a file is excluded from the .ctx cache —
build artifacts, lockfiles, and (by default) test files. It's pure and
has no I/O, so it's a good first unit to cover.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from init_cache import should_skip  # noqa: E402

DEFAULT_CFG = {"include_tests": False, "exclude_patterns": []}


def test_regular_source_file_is_kept():
    assert should_skip(Path("src/app.py"), DEFAULT_CFG) is False


def test_always_skip_dir_name_is_skipped():
    assert should_skip(Path("node_modules"), DEFAULT_CFG) is True
    assert should_skip(Path("__pycache__"), DEFAULT_CFG) is True


def test_skip_extension_is_skipped():
    assert should_skip(Path("package-lock.lock"), DEFAULT_CFG) is True
    assert should_skip(Path("bundle.min.js"), DEFAULT_CFG) is True


def test_test_file_skipped_by_default():
    assert should_skip(Path("src/app.test.js"), DEFAULT_CFG) is True
    assert should_skip(Path("src/app_spec.rb"), DEFAULT_CFG) is True


def test_test_dir_skipped_by_default():
    assert should_skip(Path("tests/test_app.py"), DEFAULT_CFG) is True
    assert should_skip(Path("__tests__/app.js"), DEFAULT_CFG) is True


def test_test_file_kept_when_include_tests_true():
    cfg = {"include_tests": True, "exclude_patterns": []}
    assert should_skip(Path("src/app.test.js"), cfg) is False
    assert should_skip(Path("tests/test_app.py"), cfg) is False


def test_exclude_pattern_skips_matching_path():
    cfg = {"include_tests": False, "exclude_patterns": [r"vendor/"]}
    assert should_skip(Path("vendor/lib.py"), cfg) is True
    assert should_skip(Path("src/lib.py"), cfg) is False
