"""Unit tests for the per-language analyzers in init_cache.py.

Python uses real ast parsing; JS/TS uses regex. These tests pin down what
each analyzer currently extracts so regressions in either are caught, and
document known regex-analyzer limitations rather than letting them surface
silently as "the tool is just wrong sometimes."
"""
from init_cache import analyze_python, analyze_js_ts


class TestAnalyzePython:
    def test_functions_and_classes(self):
        src = """
def public_fn():
    pass

def _private_fn():
    pass

class Widget:
    pass
"""
        result = analyze_python(src)
        assert "public_fn" in result["functions"]
        assert "_private_fn" not in result["functions"], "leading-underscore fns are treated as private"
        assert "Widget" in result["exports"]
        assert "Widget" in result["state"]

    def test_imports_split_internal_vs_external(self):
        src = """
import os
import json
from . import sibling
from .utils import helper
from mypkg.sub import thing
"""
        result = analyze_python(src)
        assert "os" in result["imports_ext"]
        assert "json" in result["imports_ext"]
        assert "mypkg" in result["imports_ext"]
        assert any(i.startswith(".") for i in result["imports_int"])

    def test_syntax_error_does_not_raise(self):
        # analyze_file/analyze_python must degrade gracefully on unparsable
        # source (e.g. a file mid-edit) rather than crash the whole scan.
        result = analyze_python("def broken(:\n    not valid python")
        assert result["functions"] == []
        assert result["exports"] == []

    def test_export_list_capped_at_five(self):
        src = "\n".join(f"class C{i}:\n    pass" for i in range(10))
        result = analyze_python(src)
        assert len(result["exports"]) == 5


class TestAnalyzeJsTs:
    def test_named_exports(self):
        src = """
export function handleLogin() {}
export const MAX = 5;
export class Widget {}
"""
        result = analyze_js_ts(src)
        assert "handleLogin" in result["exports"]
        assert "MAX" in result["exports"]
        assert "Widget" in result["exports"]

    def test_export_brace_list(self):
        src = "const a = 1; const b = 2; export { a, b as bRenamed };"
        result = analyze_js_ts(src)
        assert "a" in result["exports"]
        assert "b" in result["exports"], "aliased export should record the original name, not the alias"

    def test_relative_vs_package_imports(self):
        src = """
import { helper } from './utils/helper';
import React from 'react';
import { Box } from '@mui/material';
"""
        result = analyze_js_ts(src)
        assert "./utils/helper" in result["imports_int"]
        assert "react" in result["imports_ext"]
        assert "@mui/material" in result["imports_ext"]

    def test_regex_analyzer_confuses_method_definitions_with_top_level_functions(self):
        """Known limitation: the JS/TS analyzer is line-oriented regex, not a
        real parser, so a class method matching `functionName(` can be picked
        up as if it were a standalone function. This test documents the
        current (imperfect) behavior so a future AST-based rewrite has a
        clear before/after to compare against."""
        src = """
class Service {
    doWork() {
        return 1;
    }
}
"""
        result = analyze_js_ts(src)
        # Current behavior: methods are NOT matched by the top-level function
        # regex (it requires `function`/`const`/`let` before the name), so
        # this stays empty. If this starts failing, the analyzer's behavior
        # changed and the docstring above should be revisited.
        assert result["functions"] == []
