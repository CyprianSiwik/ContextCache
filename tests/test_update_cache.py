"""Tests for update_cache.py's incremental event handling, including
regression tests for two bugs found and fixed during review:

  1. extract_file_block() matched a §F path as a bare substring, so deleting
     "src/a.ts" could also match "src/a.tsx".
  2. remove_from_dir_block() did the same for filenames inside a collapsed
     §D block, and used a *global* substitution — so deleting "utils.ts"
     silently erased "utils.tsx" too. This was real data loss, not just a
     wrong match.
"""
from pathlib import Path

from update_cache import (
    extract_file_block,
    remove_from_dir_block,
    append_note,
    handle_delete,
)

FAKE_HEADER = "@ctx v1 demo\n%updated 2026-01-01T00:00:00Z\n\n"


class TestFilenamePrefixCollisions:
    def test_extract_file_block_does_not_match_longer_sibling_path(self):
        content = (
            FAKE_HEADER
            + "§F\np src/a.ts t ts sz 2\n  ex a\n\n"
            + "§F\np src/a.tsx t tsx sz 2\n  ex b\n\n"
            + "§N\n"
        )
        start, end = extract_file_block(content, "src/a.ts")
        block = content[start:end]
        assert "src/a.ts " in block or block.rstrip().endswith("src/a.ts")
        assert "a.tsx" not in block

    def test_delete_utils_ts_leaves_utils_tsx_block_intact(self):
        content = (
            FAKE_HEADER
            + "§F\np src/utils.ts t ts sz 2\n  ex a\n\n"
            + "§F\np src/utils.tsx t tsx sz 2\n  ex b\n\n"
            + "§N\n"
        )
        result = handle_delete(content, "src/utils.ts")
        assert "src/utils.ts " not in result
        assert "src/utils.tsx" in result
        assert "ex b" in result

    def test_remove_from_dir_block_does_not_wipe_sibling_with_shared_prefix(self):
        content = (
            FAKE_HEADER
            + "§D src/many\n  utils.ts t ts sz 2\n  utils.tsx t tsx sz 2\n  other.py t py sz 5\n\n"
            + "§N\n"
        )
        result = remove_from_dir_block(content, "src/many/utils.ts")
        assert "utils.ts " not in result
        assert "utils.tsx" in result
        assert "other.py" in result

    def test_remove_from_dir_block_star_marker_entries(self):
        # T2 entries in a §D block are rendered as "filename* extras" (no
        # space before the *), so the boundary check must also accept "*".
        content = (
            FAKE_HEADER
            + "§D src\n  utils.ts* ex:a dep 2\n  utils.tsx* ex:b dep 1\n\n"
            + "§N\n"
        )
        result = remove_from_dir_block(content, "src/utils.ts")
        assert "utils.ts*" not in result
        assert "utils.tsx*" in result

    def test_normal_delete_with_no_collision_still_works(self):
        content = (
            FAKE_HEADER
            + "§D src\n  a.py t py sz 1\n  b.py t py sz 2\n\n"
            + "§N\n"
        )
        result = remove_from_dir_block(content, "src/a.py")
        assert "a.py" not in result
        assert "b.py" in result


class TestNoteAppending:
    def test_append_note_adds_tagged_line(self):
        content = FAKE_HEADER + "§N\nexisting note\n"
        result = append_note(content, "arch", "JWT stored in Redis")
        assert "#arch] JWT stored in Redis" in result
        assert "existing note" in result

    def test_append_note_creates_section_when_missing(self):
        content = FAKE_HEADER + "§F\np a.py t py sz 1\n"
        result = append_note(content, "todo", "add rate limiting")
        assert "§N" in result
        assert "#todo] add rate limiting" in result


class TestIdempotency:
    def test_deleting_same_file_twice_is_a_noop_second_time(self):
        content = FAKE_HEADER + "§F\np a.py t py sz 1\n\n§N\n"
        once = handle_delete(content, "a.py")
        twice = handle_delete(once, "a.py")
        assert once == twice
