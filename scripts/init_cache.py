#!/usr/bin/env python3
"""
init_cache.py — Generate a .ctx context cache file for a project.

Usage:
    python init_cache.py [project_root] [--output .ctx] [--config .ctxconfig]

Two-pass approach:
  Pass 1 — scan all files, collect imports/exports, build dependency graph
  Pass 2 — score every file by centrality, assign tier, render accordingly

Tiers:
  T1 (top percentile OR entry point) — full §F block with all fields
  T2 (mid percentile)              — compact §F block (exports + dep only)
  T3 (bottom percentile)           — bare tree line inside a §D group block

See references/schema.md for format spec.
"""

import os
import json
import ast
import re
import subprocess
import argparse
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

# ── Constants ──────────────────────────────────────────────────────────────────

DEFAULT_CONFIG = {
    "include_tests": False,
    "include_dirs": [],
    "exclude_patterns": [],
    "max_file_lines_for_detail": 500,
    "collapse_unchanged_after_days": 7,
    "auto_update_on": ["file_write", "file_delete", "git_commit"],
    # Percentile cutoffs for tier assignment (applied across all scanned files)
    # top tier1_percentile% -> T1, next band -> T2, remainder -> T3
    # T3 only activates when enough files exist to justify collapsing
    "tier1_percentile": 25,
    "tier2_percentile": 70,
    "floor_for_t3": 15,      # min total files before any file drops to T3
    "floor_dir_for_t3": 6,   # min files in a dir before that dir collapses to §D
}

ALWAYS_SKIP = {
    "dist", "build", ".next", "__pycache__", ".git", "node_modules",
    ".turbo", ".vercel", "coverage", ".cache", "out", ".svelte-kit",
    ".claude",
}

SKIP_EXTENSIONS = {".lock", ".map", ".min.js", ".min.css", ".pyc"}

SOURCE_EXTENSIONS = {
    ".ts": "ts", ".tsx": "tsx", ".js": "js", ".jsx": "jsx",
    ".py": "py", ".go": "go", ".rs": "rs", ".rb": "rb",
    ".java": "java", ".kt": "kt", ".swift": "swift",
    ".c": "c", ".cpp": "cpp", ".h": "h",
    ".css": "css", ".scss": "scss", ".html": "html",
    ".json": "json", ".yaml": "yaml", ".yml": "yaml",
    ".toml": "toml", ".md": "md", ".sql": "sql", ".sh": "sh",
}

CONFIG_FILES = {
    "package.json", "tsconfig.json", "pyproject.toml", "setup.py",
    "Cargo.toml", "go.mod", "Makefile", "Dockerfile",
    ".env.example", "vite.config.ts", "vite.config.js",
    "next.config.js", "next.config.ts", "webpack.config.js",
    "jest.config.js", "jest.config.ts", ".eslintrc.json",
}

# Entry point filenames — always promoted to Tier 1 regardless of score
ENTRY_POINT_NAMES = {
    "index.ts", "index.tsx", "index.js", "index.jsx",
    "main.ts", "main.tsx", "main.js", "main.py",
    "app.ts", "app.tsx", "app.js", "app.jsx", "app.py",
    "server.ts", "server.js",
    "cli.ts", "cli.js", "cli.py",
    "__init__.py", "__main__.py",
    "routes.ts", "routes.js", "router.ts", "router.js",
}

MAX_LIST_ITEMS = 5


# ── Config ─────────────────────────────────────────────────────────────────────

def load_config(root: Path) -> dict:
    cfg_path = root / ".ctxconfig"
    cfg = dict(DEFAULT_CONFIG)
    if cfg_path.exists():
        try:
            loaded = json.loads(cfg_path.read_text())
            cfg.update(loaded)
        except Exception:
            pass
    return cfg


# ── Git helpers ────────────────────────────────────────────────────────────────

def git_info(root: Path) -> Optional[dict]:
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
        dirty = [f for f in dirty_raw.splitlines() if f] if dirty_raw else []
        return {"branch": branch, "commit": commit_hash, "message": commit_msg, "dirty": dirty}
    except Exception:
        return None


# ── Language analysis ──────────────────────────────────────────────────────────

def analyze_python(content: str) -> dict:
    exports, functions, imports_int, imports_ext, state = [], [], [], [], []
    try:
        tree = ast.parse(content)
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                if not node.name.startswith("_"):
                    functions.append(node.name)
            elif isinstance(node, ast.ClassDef):
                exports.append(node.name)
                state.append(node.name)
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    imports_ext.append(alias.name.split(".")[0])
            elif isinstance(node, ast.ImportFrom):
                if node.module and node.level == 0:
                    imports_ext.append(node.module.split(".")[0])
                elif node.level and node.level > 0:
                    imports_int.append(f"{'.' * node.level}{node.module or ''}")
    except Exception:
        pass
    return {
        "exports": list(dict.fromkeys(exports + functions))[:MAX_LIST_ITEMS],
        "functions": list(dict.fromkeys(functions))[:MAX_LIST_ITEMS],
        "imports_int": list(dict.fromkeys(imports_int))[:MAX_LIST_ITEMS],
        "imports_ext": list(dict.fromkeys(imports_ext))[:MAX_LIST_ITEMS],
        "state": list(dict.fromkeys(state))[:MAX_LIST_ITEMS],
    }


def analyze_js_ts(content: str) -> dict:
    exports, functions, imports_int, imports_ext, state = [], [], [], [], []

    for m in re.finditer(
        r'export\s+(?:default\s+)?(?:function|class|const|let|var|type|interface|enum)\s+(\w+)', content
    ):
        exports.append(m.group(1))
    for m in re.finditer(r'export\s*\{([^}]+)\}', content):
        names = [n.strip().split(" as ")[0].strip() for n in m.group(1).split(",") if n.strip()]
        exports.extend(names)
    for m in re.finditer(r'(?:function|const|let)\s+(\w+)\s*(?:=\s*(?:async\s*)?\(|\()', content):
        functions.append(m.group(1))
    for m in re.finditer(r'class\s+(\w+)', content):
        state.append(m.group(1))
    for m in re.finditer(r"import\s+.*?from\s+['\"]([^'\"]+)['\"]", content):
        src = m.group(1)
        if src.startswith("."):
            imports_int.append(src)
        else:
            parts = src.split("/")
            imports_ext.append("/".join(parts[:2]) if src.startswith("@") else parts[0])

    return {
        "exports": list(dict.fromkeys(exports))[:MAX_LIST_ITEMS],
        "functions": list(dict.fromkeys(functions))[:MAX_LIST_ITEMS],
        "imports_int": list(dict.fromkeys(imports_int))[:MAX_LIST_ITEMS],
        "imports_ext": list(dict.fromkeys(imports_ext))[:MAX_LIST_ITEMS],
        "state": list(dict.fromkeys(state))[:MAX_LIST_ITEMS],
    }


def analyze_go(content: str) -> dict:
    exports, functions, imports_ext, state = [], [], [], []

    # Single and block imports
    block = re.search(r'import\s+\(([^)]+)\)', content, re.DOTALL)
    if block:
        for m in re.finditer(r'"([^"]+)"', block.group(1)):
            imports_ext.append(m.group(1).split("/")[-1])
    for m in re.finditer(r'^import\s+"([^"]+)"', content, re.MULTILINE):
        imports_ext.append(m.group(1).split("/")[-1])

    # Types — exported if uppercase
    for m in re.finditer(r'^type\s+(\w+)\s+(?:struct|interface)', content, re.MULTILINE):
        name = m.group(1)
        state.append(name)
        if name[0].isupper():
            exports.append(name)

    # Functions — exported if uppercase
    for m in re.finditer(r'^func\s+(?:\([^)]+\)\s+)?(\w+)\s*\(', content, re.MULTILINE):
        name = m.group(1)
        functions.append(name)
        if name[0].isupper():
            exports.append(name)

    return {
        "exports": list(dict.fromkeys(exports))[:MAX_LIST_ITEMS],
        "functions": list(dict.fromkeys(functions))[:MAX_LIST_ITEMS],
        "imports_int": [],
        "imports_ext": list(dict.fromkeys(imports_ext))[:MAX_LIST_ITEMS],
        "state": list(dict.fromkeys(state))[:MAX_LIST_ITEMS],
    }


def analyze_kotlin(content: str) -> dict:
    exports, functions, imports_ext, state = [], [], [], []

    for m in re.finditer(r'^import\s+([\w.]+)', content, re.MULTILINE):
        imports_ext.append(m.group(1).split(".")[-1])

    for m in re.finditer(
        r'(?:private\s+|internal\s+|protected\s+)?'
        r'(?:data\s+|sealed\s+|abstract\s+|open\s+)?'
        r'(?:class|object|interface|enum\s+class)\s+(\w+)',
        content
    ):
        name = m.group(1)
        state.append(name)
        exports.append(name)

    for m in re.finditer(r'(private\s+|protected\s+)?(?:suspend\s+)?fun\s+(\w+)', content):
        if not m.group(1) and not m.group(2).startswith("_"):
            functions.append(m.group(2))

    return {
        "exports": list(dict.fromkeys(exports))[:MAX_LIST_ITEMS],
        "functions": list(dict.fromkeys(functions))[:MAX_LIST_ITEMS],
        "imports_int": [],
        "imports_ext": list(dict.fromkeys(imports_ext))[:MAX_LIST_ITEMS],
        "state": list(dict.fromkeys(state))[:MAX_LIST_ITEMS],
    }


def analyze_java(content: str) -> dict:
    exports, functions, imports_ext, state = [], [], [], []

    for m in re.finditer(r'^import\s+(?:static\s+)?([\w.]+);', content, re.MULTILINE):
        parts = m.group(1).split(".")
        imports_ext.append(parts[-2] if len(parts) >= 2 else parts[-1])

    for m in re.finditer(
        r'(?:public\s+|protected\s+)?(?:abstract\s+|final\s+)?'
        r'(?:class|interface|enum|record)\s+(\w+)',
        content
    ):
        name = m.group(1)
        state.append(name)
        exports.append(name)

    for m in re.finditer(
        r'public\s+(?:static\s+)?(?:final\s+)?(?:[\w<>\[\]]+)\s+(\w+)\s*\(',
        content
    ):
        name = m.group(1)
        if name not in ("class", "interface", "enum", "record"):
            functions.append(name)

    return {
        "exports": list(dict.fromkeys(exports))[:MAX_LIST_ITEMS],
        "functions": list(dict.fromkeys(functions))[:MAX_LIST_ITEMS],
        "imports_int": [],
        "imports_ext": list(dict.fromkeys(imports_ext))[:MAX_LIST_ITEMS],
        "state": list(dict.fromkeys(state))[:MAX_LIST_ITEMS],
    }


def analyze_ruby(content: str) -> dict:
    exports, functions, imports_int, imports_ext, state = [], [], [], [], []

    for m in re.finditer(r"^require_relative\s+['\"]([^'\"]+)['\"]", content, re.MULTILINE):
        imports_int.append(m.group(1))
    for m in re.finditer(r"^require\s+['\"]([^'\"]+)['\"]", content, re.MULTILINE):
        imports_ext.append(m.group(1))

    for m in re.finditer(r'^(?:class|module)\s+(\w+)', content, re.MULTILINE):
        name = m.group(1)
        state.append(name)
        exports.append(name)

    for m in re.finditer(r'^\s+def\s+(?:self\.)?(\w+)', content, re.MULTILINE):
        name = m.group(1)
        if not name.startswith("_"):
            functions.append(name)

    return {
        "exports": list(dict.fromkeys(exports))[:MAX_LIST_ITEMS],
        "functions": list(dict.fromkeys(functions))[:MAX_LIST_ITEMS],
        "imports_int": list(dict.fromkeys(imports_int))[:MAX_LIST_ITEMS],
        "imports_ext": list(dict.fromkeys(imports_ext))[:MAX_LIST_ITEMS],
        "state": list(dict.fromkeys(state))[:MAX_LIST_ITEMS],
    }


def analyze_rust(content: str) -> dict:
    exports, functions, imports_ext, state = [], [], [], []

    for m in re.finditer(r'^use\s+([\w:]+)', content, re.MULTILINE):
        root = m.group(1).split("::")[0]
        if root not in ("crate", "super", "self"):
            imports_ext.append(root)

    for m in re.finditer(
        r'(?:pub\s+)?(?:struct|enum|trait|type|union)\s+(\w+)', content
    ):
        name = m.group(1)
        state.append(name)
    for m in re.finditer(r'pub\s+(?:struct|enum|trait|type|union)\s+(\w+)', content):
        exports.append(m.group(1))

    for m in re.finditer(r'(?:pub\s+)?(?:async\s+)?fn\s+(\w+)', content):
        name = m.group(1)
        if not name.startswith("_"):
            functions.append(name)
    for m in re.finditer(r'pub\s+(?:async\s+)?fn\s+(\w+)', content):
        exports.append(m.group(1))

    return {
        "exports": list(dict.fromkeys(exports))[:MAX_LIST_ITEMS],
        "functions": list(dict.fromkeys(functions))[:MAX_LIST_ITEMS],
        "imports_int": [],
        "imports_ext": list(dict.fromkeys(imports_ext))[:MAX_LIST_ITEMS],
        "state": list(dict.fromkeys(state))[:MAX_LIST_ITEMS],
    }


def analyze_c(content: str) -> dict:
    functions, imports_ext, state = [], [], []

    for m in re.finditer(r'^#include\s+[<"]([^>"]+)[>"]', content, re.MULTILINE):
        header = m.group(1).split("/")[-1].removesuffix(".h")
        imports_ext.append(header)

    for m in re.finditer(r'(?:class|struct|enum)\s+(\w+)', content):
        state.append(m.group(1))

    # Function definitions: type name(...) { — exclude control flow keywords
    _CF = {"if", "for", "while", "switch", "do"}
    for m in re.finditer(
        r'^(?:[\w:*&<>\s]+)\s+(\w+)\s*\([^;]*\)\s*(?:const\s*)?\{',
        content, re.MULTILINE
    ):
        name = m.group(1)
        if name not in _CF and not name.startswith("_"):
            functions.append(name)

    return {
        "exports": list(dict.fromkeys(state))[:MAX_LIST_ITEMS],
        "functions": list(dict.fromkeys(functions))[:MAX_LIST_ITEMS],
        "imports_int": [],
        "imports_ext": list(dict.fromkeys(imports_ext))[:MAX_LIST_ITEMS],
        "state": list(dict.fromkeys(state))[:MAX_LIST_ITEMS],
    }


def analyze_swift(content: str) -> dict:
    exports, functions, imports_ext, state = [], [], [], []

    for m in re.finditer(r'^import\s+(\w+)', content, re.MULTILINE):
        imports_ext.append(m.group(1))

    # Types: class/struct/enum/protocol/actor — all are navigable exports
    for m in re.finditer(
        r'(?:public\s+|open\s+|internal\s+|private\s+|fileprivate\s+)?'
        r'(?:final\s+)?(?:class|struct|enum|protocol|actor)\s+(\w+)',
        content
    ):
        name = m.group(1)
        state.append(name)
        exports.append(name)

    # Functions — skip private/fileprivate, skip underscore-prefixed
    for m in re.finditer(
        r'(private|fileprivate)?\s*(?:static\s+|class\s+|override\s+)?func\s+(\w+)',
        content
    ):
        if not m.group(1) and not m.group(2).startswith("_"):
            functions.append(m.group(2))

    return {
        "exports": list(dict.fromkeys(exports))[:MAX_LIST_ITEMS],
        "functions": list(dict.fromkeys(functions))[:MAX_LIST_ITEMS],
        "imports_int": [],
        "imports_ext": list(dict.fromkeys(imports_ext))[:MAX_LIST_ITEMS],
        "state": list(dict.fromkeys(state))[:MAX_LIST_ITEMS],
    }


def analyze_file(path: Path, lang: str) -> dict:
    try:
        content = path.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return {}
    if lang in ("ts", "tsx", "js", "jsx"):
        return analyze_js_ts(content)
    if lang == "py":
        return analyze_python(content)
    if lang == "swift":
        return analyze_swift(content)
    if lang == "go":
        return analyze_go(content)
    if lang in ("kt",):
        return analyze_kotlin(content)
    if lang == "java":
        return analyze_java(content)
    if lang == "rb":
        return analyze_ruby(content)
    if lang == "rs":
        return analyze_rust(content)
    if lang in ("c", "cpp", "h"):
        return analyze_c(content)
    return {}


# ── Helpers ────────────────────────────────────────────────────────────────────

def count_lines(path: Path) -> int:
    try:
        return path.read_text(encoding="utf-8", errors="ignore").count("\n") + 1
    except Exception:
        return 0


def should_skip(path: Path, cfg: dict) -> bool:
    if path.name in ALWAYS_SKIP:
        return True
    for ext in SKIP_EXTENSIONS:
        if path.name.endswith(ext):
            return True
    if not cfg.get("include_tests"):
        name = path.name
        if any(x in name for x in (".test.", ".spec.", "_test.", "_spec.")):
            return True
        if path.parent.name in ("__tests__", "tests", "test", "spec"):
            return True
    for pattern in cfg.get("exclude_patterns", []):
        if re.search(pattern, str(path)):
            return True
    return False


def truncate_list(items: list, label: str) -> str:
    if not items:
        return ""
    if len(items) <= MAX_LIST_ITEMS:
        return f"{label} {','.join(items)}"
    shown = items[:MAX_LIST_ITEMS]
    extra = len(items) - MAX_LIST_ITEMS
    return f"{label} {','.join(shown)}+{extra}"


def read_package_json(root: Path) -> list:
    pj = root / "package.json"
    if not pj.exists():
        return []
    try:
        data = json.loads(pj.read_text())
        deps = list(data.get("dependencies", {}).keys())[:8]
        return [f"{d}@{data['dependencies'][d].lstrip('^~')}" for d in deps]
    except Exception:
        return []


def is_entry_point(rel_path: str) -> bool:
    filename = rel_path.split("/")[-1]
    return filename in ENTRY_POINT_NAMES


TRIVIAL_ENTRY_THRESHOLD = 5

def is_trivial_entry_point(rel_path: str, data: dict) -> bool:
    """Entry point with no meaningful content — collapses to T3 so it folds into its §D group."""
    if not is_entry_point(rel_path):
        return False
    analysis = data["analysis"]
    return (
        data["line_count"] <= TRIVIAL_ENTRY_THRESHOLD
        and not analysis.get("exports")
        and not analysis.get("functions")
    )


# ── Pass 1: Scan ───────────────────────────────────────────────────────────────

def scan_project(root: Path, cfg: dict) -> dict:
    """
    Walk the project tree. For each source file collect analysis + metadata.
    Returns dict keyed by rel_path. Does NOT score or tier — that is Pass 2.
    """
    include_dirs = cfg.get("include_dirs", [])
    files = {}

    for dirpath, dirnames, filenames in os.walk(root):
        dp = Path(dirpath)
        rel_dir = dp.relative_to(root)

        dirnames[:] = [
            d for d in dirnames
            if d not in ALWAYS_SKIP and not (dp / d / "SKILL.md").exists()
        ]
        if include_dirs and rel_dir == Path("."):
            dirnames[:] = [d for d in dirnames if d in include_dirs]

        for fname in filenames:
            fpath = dp / fname
            if should_skip(fpath, cfg):
                continue
            suffix = fpath.suffix.lower()
            lang = SOURCE_EXTENSIONS.get(suffix)
            if not lang:
                continue
            rel_str = str(fpath.relative_to(root)).replace("\\", "/")
            files[rel_str] = {
                "path": fpath,
                "lang": lang,
                "analysis": analyze_file(fpath, lang),
                "line_count": count_lines(fpath),
            }

    return files


# ── Pass 1b: Build dependency graph ───────────────────────────────────────────

def resolve_import(import_str: str, importer_path: str, known_paths: set) -> Optional[str]:
    """Resolve a relative import string to a known rel_path, or None."""
    dir_parts = importer_path.split("/")[:-1]
    clean = import_str.lstrip("./")
    dots = len(import_str) - len(import_str.lstrip("."))
    go_up = max(0, dots - 1)
    base_parts = dir_parts[:len(dir_parts) - go_up] if go_up else dir_parts
    candidate_base = "/".join(base_parts + [clean]) if clean else "/".join(base_parts)

    for ext in (".ts", ".tsx", ".js", ".jsx", ".py"):
        candidate = candidate_base + ext
        if candidate in known_paths:
            return candidate
    for idx in ("index.ts", "index.tsx", "index.js", "__init__.py"):
        candidate = candidate_base + "/" + idx
        if candidate in known_paths:
            return candidate
    return None


def build_dep_graph(files: dict) -> dict:
    """
    Invert the import map: rel_path -> count of files that import it.
    """
    known_paths = set(files.keys())
    depended_on_by = defaultdict(set)

    for rel_path, data in files.items():
        for imp in data["analysis"].get("imports_int", []):
            resolved = resolve_import(imp, rel_path, known_paths)
            if resolved:
                depended_on_by[resolved].add(rel_path)

    return {path: len(importers) for path, importers in depended_on_by.items()}


# ── Pass 2: Score and tier ─────────────────────────────────────────────────────

def score_file(rel_path: str, data: dict, dep_counts: dict) -> int:
    """
    importance = dep_count + export_count + import_count
    dep_count    — how many files import this one (load-bearing?)
    export_count — surface area exposed
    import_count — things this file orchestrates / calls
    """
    analysis     = data["analysis"]
    dep_count    = dep_counts.get(rel_path, 0)
    export_count = len(analysis.get("exports", []))
    import_count = (
        len(analysis.get("imports_int", [])) +
        len(analysis.get("imports_ext", []))
    )
    return dep_count + export_count + import_count


def compute_percentile_thresholds(scores: dict, cfg: dict) -> tuple:
    """
    Given a dict of rel_path -> score, compute the absolute score values that
    correspond to the configured percentile cutoffs.

    Returns (t1_min, t2_min) — the minimum score to qualify for each tier.
    Entry points bypass these thresholds entirely (always T1).

    Floor guard: if total file count < floor_for_t3, nobody drops to T3 —
    we shift the T2/T3 boundary down to 0 so every non-entry file gets at
    least T2.
    """
    t1_pct = cfg.get("tier1_percentile", 25)
    t2_pct = cfg.get("tier2_percentile", 70)
    floor  = cfg.get("floor_for_t3", 15)

    values = sorted(scores.values(), reverse=True)  # high -> low
    n = len(values)

    if n == 0:
        return 0, 0

    # Index of the cutoff: top X% means the first (X/100 * n) files
    t1_idx = max(0, int(n * t1_pct / 100) - 1)
    t2_idx = max(0, int(n * t2_pct / 100) - 1)

    t1_min = values[t1_idx] if values else 0
    t2_min = values[t2_idx] if values else 0

    # Floor guard: if too few files, collapse T3 by setting t2_min to 0
    # so everything scores >= t2_min and lands in T1 or T2 at worst
    if n < floor:
        t2_min = 0

    # Edge: if all scores are equal, everyone is T1
    if t1_min == t2_min == (values[0] if values else 0):
        t2_min = 0

    return t1_min, t2_min


def assign_tiers(files: dict, dep_counts: dict, cfg: dict) -> dict:
    """
    Score all files, compute percentile thresholds, assign tiers.
    Returns dict: rel_path -> (data, score, tier)
    Entry points always get T1 regardless of score.
    """
    scores = {
        rel_path: score_file(rel_path, data, dep_counts)
        for rel_path, data in files.items()
    }

    t1_min, t2_min = compute_percentile_thresholds(scores, cfg)

    result = {}
    for rel_path, data in files.items():
        score = scores[rel_path]
        if is_entry_point(rel_path) and not is_trivial_entry_point(rel_path, data):
            tier = 1
        elif score >= t1_min:
            tier = 1
        elif score >= t2_min:
            tier = 2
        else:
            tier = 3
        result[rel_path] = (data, score, tier)

    return result


def assign_tier_single(rel_path: str, score: int, all_scores: dict, cfg: dict, data: dict = None) -> int:
    """
    Assign a tier for a single file given the full score map.
    Used by update_cache when rescoring after a write event.
    """
    if is_entry_point(rel_path) and not (data and is_trivial_entry_point(rel_path, data)):
        return 1
    t1_min, t2_min = compute_percentile_thresholds(all_scores, cfg)
    if score >= t1_min:
        return 1
    if score >= t2_min:
        return 2
    return 3


# ── Block builders ─────────────────────────────────────────────────────────────

def build_git_block(info: dict) -> str:
    lines = ["§G"]
    lines.append(f"branch {info['branch']}")
    lines.append(f"commit {info['commit']} \"{info['message']}\"")
    if info.get("dirty"):
        lines.append(f"dirty {','.join(info['dirty'][:10])}")
    return "\n".join(lines)


def build_config_block(root: Path) -> str:
    found = [f"p {name}" for name in CONFIG_FILES if (root / name).exists()]
    if not found:
        return ""
    return "§C\n" + "\n".join(found)


def build_external_deps_block(root: Path) -> str:
    deps = read_package_json(root)
    if not deps:
        return ""
    return "§X " + " ".join(deps)


def build_tier1_block(rel_path: str, data: dict, dep_counts: dict) -> str:
    """Full §F block — all fields."""
    analysis = data["analysis"]
    lc = data["line_count"]
    lines = [f"§F\np {rel_path} t {data['lang']} sz {lc}"]

    if analysis.get("exports"):
        lines.append("  " + truncate_list(analysis["exports"], "ex"))
    if analysis.get("imports_int"):
        cleaned = [i.lstrip("./") for i in analysis["imports_int"]]
        lines.append("  " + truncate_list(cleaned, "im"))
    if analysis.get("imports_ext"):
        lines.append("  " + truncate_list(analysis["imports_ext"], "xi"))
    if analysis.get("functions"):
        lines.append("  " + truncate_list(analysis["functions"], "fn"))
    if analysis.get("state"):
        lines.append("  " + truncate_list(analysis["state"], "st"))
    dep_count = dep_counts.get(rel_path, 0)
    if dep_count > 0:
        lines.append(f"  dep {dep_count}")

    return "\n".join(lines)


def build_tier2_block(rel_path: str, data: dict, dep_counts: dict) -> str:
    """Compact §F block — exports and dep count only."""
    analysis = data["analysis"]
    lc = data["line_count"]
    lines = [f"§F\np {rel_path} t {data['lang']} sz {lc}"]

    if analysis.get("exports"):
        lines.append("  " + truncate_list(analysis["exports"], "ex"))
    dep_count = dep_counts.get(rel_path, 0)
    if dep_count > 0:
        lines.append(f"  dep {dep_count}")

    return "\n".join(lines)



def infer_t3_hint(filename: str, analysis: dict) -> str:
    """
    Generate a minimal navigation hint for a T3 file.
    Priority: exports > filename pattern > empty string.
    Goal: one short signal so Claude can route without reading the file.
    """
    # If it has exports, use them — they're the best signal
    exs = analysis.get("exports", [])
    if exs:
        return truncate_list(exs[:3], "ex")  # cap at 3 for T3

    # Filename pattern hints — map common names to short descriptions
    stem = filename.lower().replace("-", "").replace("_", "").replace(".", "")
    HINTS = {
        "constants":   "# constants",
        "config":      "# config",
        "types":       "# types",
        "interfaces":  "# types",
        "helpers":     "# helpers",
        "utils":       "# helpers",
        "logger":      "# logging",
        "log":         "# logging",
        "errors":      "# error defs",
        "exceptions":  "# error defs",
        "middleware":  "# middleware",
        "validators":  "# validation",
        "validation":  "# validation",
        "schema":      "# schema",
        "migrations":  "# migration",
        "seeds":       "# seed data",
        "fixtures":    "# fixtures",
        "mocks":       "# mocks",
        "stubs":       "# stubs",
        "setup":       "# setup",
        "teardown":    "# teardown",
        "hooks":       "# hooks",
        "context":     "# context",
        "store":       "# state",
        "state":       "# state",
        "reducer":     "# reducer",
        "actions":     "# actions",
        "selectors":   "# selectors",
        "styles":      "# styles",
        "theme":       "# theme",
        "colors":      "# theme",
        "fonts":       "# theme",
        "icons":       "# icons",
        "assets":      "# assets",
        "env":         "# env vars",
        "environment": "# env vars",
        "database":    "# db config",
        "db":          "# db config",
        "cache":       "# cache",
        "queue":       "# queue",
        "worker":      "# worker",
        "job":         "# job",
        "cron":        "# cron",
        "event":       "# events",
        "events":      "# events",
        "handler":     "# handler",
        "handlers":    "# handlers",
        "controller":  "# controller",
        "service":     "# service",
        "repository":  "# data access",
        "repo":        "# data access",
        "model":       "# model",
        "entity":      "# entity",
        "dto":         "# dto",
        "serializer":  "# serializer",
        "formatter":   "# formatter",
        "parser":      "# parser",
        "transformer": "# transform",
        "adapter":     "# adapter",
        "factory":     "# factory",
        "builder":     "# builder",
        "provider":    "# provider",
        "registry":    "# registry",
        "plugin":      "# plugin",
        "extension":   "# extension",
        "decorator":   "# decorator",
        "guard":       "# guard",
        "interceptor": "# interceptor",
        "filter":      "# filter",
        "pipe":        "# pipe",
    }
    for key, hint in HINTS.items():
        if key in stem:
            return hint

    return ""  # truly unknown — bare filename is fine


def build_dir_group_block(dir_path: str, entries: list, dep_counts: dict) -> tuple:
    """
    §D group for T2/T3 files in a directory.
    T2 files get a * inline mini-summary (filename + exports + dep count).
    T3 files get a minimal hint: exports if any, else a filename-pattern comment.
    Returns (block_str, promoted_list) where promoted is any T1 that snuck in.
    """
    lines = [f"§D {dir_path}"]
    promoted = []

    for rel_path, data, score, tier in entries:
        filename = rel_path.split("/")[-1]
        if tier == 1:
            promoted.append((rel_path, data, score))
        elif tier == 2:
            analysis = data["analysis"]
            exs = analysis.get("exports", [])
            dep_count = dep_counts.get(rel_path, 0)
            ex_str  = truncate_list(exs, "ex") if exs else ""
            dep_str = f"dep {dep_count}" if dep_count else ""
            extras  = " ".join(filter(None, [ex_str, dep_str]))
            lines.append(f"  {filename}* {extras}".rstrip())
        else:
            hint = infer_t3_hint(filename, data["analysis"])
            line = f"  {filename} {hint}".rstrip()
            lines.append(line)

    return "\n".join(lines), promoted


# ── Main generation ────────────────────────────────────────────────────────────

def generate_ctx(root: Path, output: Path, cfg: dict) -> str:
    project_name = root.name
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    blocks = []
    blocks.append(f"@ctx v1 {project_name}\n%updated {now}")

    git = git_info(root)
    if git:
        blocks.append(build_git_block(git))

    cfg_block = build_config_block(root)
    if cfg_block:
        blocks.append(cfg_block)

    ext_block = build_external_deps_block(root)
    if ext_block:
        blocks.append(ext_block)

    # ── Pass 1 ────────────────────────────────────────────────────────────────
    files = scan_project(root, cfg)

    # ── Pass 1b ───────────────────────────────────────────────────────────────
    dep_counts = build_dep_graph(files)

    # ── Pass 2: percentile tier assignment ──────────────────────────────────
    scored = assign_tiers(files, dep_counts, cfg)

    # ── Group by directory ────────────────────────────────────────────────────
    by_dir = defaultdict(list)
    for rel_path, (data, score, tier) in scored.items():
        dir_key = "/".join(rel_path.split("/")[:-1]) or "."
        by_dir[dir_key].append((rel_path, data, score, tier))

    # ── Render ────────────────────────────────────────────────────────────────
    max_lines    = cfg.get("max_file_lines_for_detail", 500)
    floor_dir_t3 = cfg.get("floor_dir_for_t3", 6)

    for dir_key in sorted(by_dir.keys()):
        entries = sorted(by_dir[dir_key], key=lambda x: x[0])

        # Per-directory floor: small dirs never collapse to T3 bare lines —
        # promote any T3s up to T2 so they at least get an inline mini-summary
        if len(entries) < floor_dir_t3:
            entries = [
                (r, d, s, 2 if t == 3 else t)
                for r, d, s, t in entries
            ]

        tiers_in_dir = [t for _, _, _, t in entries]
        all_t1 = all(t == 1 for t in tiers_in_dir)

        if all_t1 or len(entries) == 1:
            for rel_path, data, score, tier in entries:
                if data["line_count"] > max_lines:
                    blocks.append(
                        f"§F\np {rel_path} t {data['lang']} sz {data['line_count']} # large — detail omitted"
                    )
                elif tier == 1:
                    blocks.append(build_tier1_block(rel_path, data, dep_counts))
                else:
                    blocks.append(build_tier2_block(rel_path, data, dep_counts))
        else:
            # Mixed dir: T1s get full blocks, T2/T3 collapse into §D group
            t1_entries    = [(r, d, s, t) for r, d, s, t in entries if t == 1]
            group_entries = [(r, d, s, t) for r, d, s, t in entries if t != 1]

            for rel_path, data, score, tier in t1_entries:
                if data["line_count"] > max_lines:
                    blocks.append(
                        f"§F\np {rel_path} t {data['lang']} sz {data['line_count']} # large — detail omitted"
                    )
                else:
                    blocks.append(build_tier1_block(rel_path, data, dep_counts))

            if group_entries:
                group_block, promoted = build_dir_group_block(dir_key, group_entries, dep_counts)
                blocks.append(group_block)
                for rel_path, data, score in promoted:
                    blocks.append(build_tier1_block(rel_path, data, dep_counts))

    blocks.append("§N\n# Agent notes will appear here after first session.")

    ctx_content = "\n\n".join(blocks) + "\n"
    output.write_text(ctx_content, encoding="utf-8")
    return ctx_content


# ── CLI ────────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Generate a .ctx context cache for a project.")
    parser.add_argument("root", nargs="?", default=".", help="Project root directory")
    parser.add_argument("--output", default=".ctx", help="Output file (default: .ctx)")
    parser.add_argument("--config", default=".ctxconfig", help="Config file")
    parser.add_argument("--show-scores", action="store_true",
                        help="Print per-file importance scores before writing")
    args = parser.parse_args()

    root   = Path(args.root).resolve()
    output = root / args.output if not Path(args.output).is_absolute() else Path(args.output)
    cfg    = load_config(root)

    print(f"Scanning {root} ...")
    files      = scan_project(root, cfg)
    dep_counts = build_dep_graph(files)

    if args.show_scores:
        scored_preview = assign_tiers(files, dep_counts, cfg)
        scores_map = {r: s for r, (d, s, t) in scored_preview.items()}
        t1_min, t2_min = compute_percentile_thresholds(scores_map, cfg)
        print(f"\n── Importance scores (T1 min={t1_min}, T2 min={t2_min}) ──")
        rows = [(s, t, r) for r, (d, s, t) in scored_preview.items()]
        for score, tier, rel_path in sorted(rows, reverse=True):
            marker = " [entry]" if is_entry_point(rel_path) else ""
            print(f"  T{tier} score={score:2d}  {rel_path}{marker}")
        print()

    content = generate_ctx(root, output, cfg)

    print(f"✓ Wrote {output}")
    print(f"  {len(files)} files scanned")
    print(f"  ~{len(content.split())} word-tokens (rough estimate)")
    print(f"  Run with --show-scores to see per-file importance scores and tiers")

if __name__ == "__main__":
    main()
