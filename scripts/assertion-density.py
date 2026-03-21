#!/usr/bin/env python3
"""Scan test files for assertion density. Flag vacuous tests (0 assertions)."""
import argparse
import ast
import json
import os
import re
import sys


def count_assertions_ast(node):
    """Count assert statements and self.assert* calls in an AST node."""
    count = 0
    for child in ast.walk(node):
        if isinstance(child, ast.Assert):
            count += 1
        elif isinstance(child, ast.Call):
            func = child.func
            if isinstance(func, ast.Attribute) and func.attr.startswith("assert"):
                count += 1
    return count


def analyze_python_file(path):
    """Parse a Python file and return per-function assertion counts."""
    with open(path) as f:
        source = f.read()

    try:
        tree = ast.parse(source, filename=path)
    except SyntaxError:
        return {"file": path, "error": "syntax_error", "functions": []}

    functions = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if not node.name.startswith("test"):
                continue
            count = count_assertions_ast(node)
            functions.append({
                "name": node.name,
                "line": node.lineno,
                "assertions": count,
                "vacuous": count == 0,
            })

    return {"file": path, "functions": functions}


SHELL_ASSERT_RE = re.compile(r"\bassert_\w+")
SHELL_FUNC_RE = re.compile(r"^(?:function\s+)?(test_\w+)\s*\(\)", re.MULTILINE)


def analyze_shell_file(path):
    """Regex-based assertion counting for shell test files."""
    with open(path) as f:
        source = f.read()

    func_starts = [(m.start(), m.group(1)) for m in SHELL_FUNC_RE.finditer(source)]
    if not func_starts:
        return {"file": path, "functions": []}

    functions = []
    for i, (start, name) in enumerate(func_starts):
        end = func_starts[i + 1][0] if i + 1 < len(func_starts) else len(source)
        block = source[start:end]
        count = len(SHELL_ASSERT_RE.findall(block))
        line = source[:start].count("\n") + 1
        functions.append({
            "name": name,
            "line": line,
            "assertions": count,
            "vacuous": count == 0,
        })

    return {"file": path, "functions": functions}


def analyze_file(path):
    """Route to the right analyzer based on file extension."""
    if path.endswith(".py"):
        return analyze_python_file(path)
    elif path.endswith(".sh") or path.endswith(".bats"):
        return analyze_shell_file(path)
    return {"file": path, "error": "unsupported_type", "functions": []}


def main():
    parser = argparse.ArgumentParser(description="Scan test files for assertion density")
    parser.add_argument("--test-files", required=True, help="Comma-separated test file paths")
    parser.add_argument("--min-density", type=float, default=0.1,
                        help="Minimum assertions-per-test ratio (default: 0.1)")
    args = parser.parse_args()

    files = [f.strip() for f in args.test_files.split(",") if f.strip()]
    results = []
    total_tests = 0
    total_assertions = 0
    vacuous_count = 0

    for path in files:
        if not os.path.isfile(path):
            results.append({"file": path, "error": "not_found", "functions": []})
            continue
        analysis = analyze_file(path)
        results.append(analysis)
        for fn in analysis.get("functions", []):
            total_tests += 1
            total_assertions += fn["assertions"]
            if fn["vacuous"]:
                vacuous_count += 1

    density = total_assertions / total_tests if total_tests > 0 else 0.0
    below_threshold = density < args.min_density

    output = {
        "files": results,
        "summary": {
            "total_tests": total_tests,
            "total_assertions": total_assertions,
            "density": round(density, 3),
            "vacuous": vacuous_count,
            "below_threshold": below_threshold,
            "threshold": args.min_density,
        },
    }

    print(json.dumps(output, indent=2))
    sys.exit(1 if vacuous_count > 0 or below_threshold else 0)


if __name__ == "__main__":
    main()
