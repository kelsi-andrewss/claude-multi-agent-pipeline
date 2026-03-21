#!/usr/bin/env python3
"""Lightweight targeted mutation testing for Python functions."""
import argparse
import ast
import copy
import json
import os
import shutil
import subprocess
import sys
import tempfile


class MutationGenerator:
    """Generate mutants for specific functions in a Python file."""

    def __init__(self, source_path, function_names):
        self.source_path = os.path.abspath(source_path)
        self.source = open(source_path).read()
        self.tree = ast.parse(self.source)
        self.function_names = set(function_names)
        self.mutants = []

    def generate(self):
        """Walk AST, find target functions, generate mutants."""
        for node in ast.walk(self.tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                if node.name in self.function_names:
                    self._mutate_comparisons(node)
                    self._mutate_booleans(node)
                    self._mutate_numbers(node)
        return self.mutants

    def _make_mutant(self, description, original_node, mutator):
        """Create a mutant by deep-copying the tree and applying a mutation."""
        tree_copy = copy.deepcopy(self.tree)
        # Find the corresponding node in the copy by line/col
        for node in ast.walk(tree_copy):
            if (type(node) == type(original_node)
                    and getattr(node, 'lineno', None) == original_node.lineno
                    and getattr(node, 'col_offset', None) == original_node.col_offset):
                mutator(node)
                try:
                    source = ast.unparse(tree_copy)
                except Exception:
                    return
                self.mutants.append({
                    "description": description,
                    "line": original_node.lineno,
                    "source": source,
                })
                return

    def _mutate_comparisons(self, func_node):
        """Flip comparison operators (== -> !=, < -> >=, etc.)."""
        flips = {
            ast.Eq: ast.NotEq,
            ast.NotEq: ast.Eq,
            ast.Lt: ast.GtE,
            ast.GtE: ast.Lt,
            ast.Gt: ast.LtE,
            ast.LtE: ast.Gt,
            ast.Is: ast.IsNot,
            ast.IsNot: ast.Is,
            ast.In: ast.NotIn,
            ast.NotIn: ast.In,
        }
        for child in ast.walk(func_node):
            if isinstance(child, ast.Compare):
                for i, op in enumerate(child.ops):
                    flip_to = flips.get(type(op))
                    if flip_to:
                        orig_op = op
                        orig_line = child.lineno

                        def mutator(node, idx=i, new_op=flip_to):
                            if isinstance(node, ast.Compare) and idx < len(node.ops):
                                node.ops[idx] = new_op()

                        self._make_mutant(
                            f"L{orig_line}: flip {type(op).__name__} -> {flip_to.__name__}",
                            child, mutator,
                        )

    def _mutate_booleans(self, func_node):
        """Swap True/False constants."""
        for child in ast.walk(func_node):
            if isinstance(child, ast.Constant) and isinstance(child.value, bool):
                orig_val = child.value

                def mutator(node, target=not orig_val):
                    if isinstance(node, ast.Constant) and isinstance(node.value, bool):
                        node.value = target

                self._make_mutant(
                    f"L{child.lineno}: flip {orig_val} -> {not orig_val}",
                    child, mutator,
                )

    def _mutate_numbers(self, func_node):
        """Change numeric constants (n -> n+1, 0 -> 1, etc.)."""
        for child in ast.walk(func_node):
            if (isinstance(child, ast.Constant)
                    and isinstance(child.value, (int, float))
                    and not isinstance(child.value, bool)):
                orig_val = child.value
                new_val = 0 if orig_val != 0 else 1

                def mutator(node, target=new_val):
                    if isinstance(node, ast.Constant):
                        node.value = target

                self._make_mutant(
                    f"L{child.lineno}: change {orig_val} -> {new_val}",
                    child, mutator,
                )


def run_mutant(source_path, mutant_source, test_cmd, test_files):
    """Run tests against a single mutant. Returns True if killed (tests fail)."""
    original = open(source_path).read()
    try:
        with open(source_path, "w") as f:
            f.write(mutant_source)

        cmd = test_cmd.split() + [f.strip() for f in test_files.split(",") if f.strip()]
        result = subprocess.run(
            cmd,
            capture_output=True, text=True, timeout=60,
            cwd=os.path.dirname(source_path) or ".",
        )
        return result.returncode != 0
    except subprocess.TimeoutExpired:
        return True  # timeout = killed
    finally:
        with open(source_path, "w") as f:
            f.write(original)


def main():
    parser = argparse.ArgumentParser(description="Targeted mutation testing")
    parser.add_argument("--target", required=True, help="Python source file to mutate")
    parser.add_argument("--functions", required=True, help="Comma-separated function names")
    parser.add_argument("--test-cmd", required=True, help="Test command (e.g. 'python3 -m pytest -x')")
    parser.add_argument("--test-files", required=True, help="Comma-separated test file paths")
    parser.add_argument("--max-mutants", type=int, default=20, help="Max mutants to test")
    args = parser.parse_args()

    if not os.path.isfile(args.target):
        print(json.dumps({"error": f"Target file not found: {args.target}"}))
        sys.exit(2)

    func_names = [f.strip() for f in args.functions.split(",") if f.strip()]

    # Work on a temp copy so we never corrupt the original on crash
    tmpdir = tempfile.mkdtemp(prefix="mutation_")
    target_basename = os.path.basename(args.target)
    target_dir = os.path.dirname(os.path.abspath(args.target))

    # Copy the entire scripts directory to temp
    tmp_target_dir = os.path.join(tmpdir, "scripts")
    shutil.copytree(target_dir, tmp_target_dir)
    tmp_target = os.path.join(tmp_target_dir, target_basename)

    gen = MutationGenerator(args.target, func_names)
    mutants = gen.generate()

    if not mutants:
        output = {
            "target": args.target,
            "functions": func_names,
            "total_mutants": 0,
            "killed": 0,
            "survived": 0,
            "score": 1.0,
            "details": [],
        }
        print(json.dumps(output, indent=2))
        sys.exit(0)

    mutants = mutants[:args.max_mutants]

    killed = 0
    survived = 0
    details = []

    for i, mutant in enumerate(mutants):
        is_killed = run_mutant(tmp_target, mutant["source"], args.test_cmd, args.test_files)
        status = "killed" if is_killed else "survived"
        if is_killed:
            killed += 1
        else:
            survived += 1
        details.append({
            "id": i + 1,
            "description": mutant["description"],
            "line": mutant["line"],
            "status": status,
        })
        print(f"  mutant {i+1}/{len(mutants)}: {status} — {mutant['description']}", file=sys.stderr)

    total = killed + survived
    score = killed / total if total > 0 else 1.0

    output = {
        "target": args.target,
        "functions": func_names,
        "total_mutants": total,
        "killed": killed,
        "survived": survived,
        "score": round(score, 3),
        "details": details,
    }

    print(json.dumps(output, indent=2))

    # Clean up temp dir
    shutil.rmtree(tmpdir, ignore_errors=True)

    sys.exit(0 if score >= 0.5 else 1)


if __name__ == "__main__":
    main()
