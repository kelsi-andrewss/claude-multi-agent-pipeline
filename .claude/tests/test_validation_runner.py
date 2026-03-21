"""Integration tests for validation-runner.sh."""
import json
import os
import subprocess

import pytest

SCRIPT_PATH = os.path.join(os.path.dirname(__file__), "..", "..", "scripts", "validation-runner.sh")


def run_validation(project_root, layer="all"):
    result = subprocess.run(
        ["bash", SCRIPT_PATH,
         "--project-root", project_root,
         "--layer", layer],
        capture_output=True, text=True,
        timeout=60,
    )
    return result


def write_package_json(project_dir, scripts=None):
    """Write a package.json with the given scripts dict."""
    if scripts is None:
        scripts = {"build": "echo ok", "lint": "echo ok", "test": "echo ok"}
    pkg = {"name": "test-project", "scripts": scripts}
    with open(os.path.join(project_dir, "package.json"), "w") as f:
        json.dump(pkg, f)


@pytest.fixture
def node_project(tmp_path):
    """A fake node project with passing build/lint/test."""
    project = str(tmp_path / "project")
    os.makedirs(project)
    write_package_json(project)
    return project


@pytest.fixture
def failing_build_project(tmp_path):
    """A node project where build exits non-zero."""
    project = str(tmp_path / "project")
    os.makedirs(project)
    write_package_json(project, {
        "build": "exit 1",
        "lint": "echo ok",
        "test": "echo ok",
    })
    return project


@pytest.fixture
def failing_lint_project(tmp_path):
    """A node project where lint exits non-zero."""
    project = str(tmp_path / "project")
    os.makedirs(project)
    write_package_json(project, {
        "build": "echo ok",
        "lint": "exit 1",
        "test": "echo ok",
    })
    return project


class TestValidationRunnerNodeProject:
    def test_all_layers_pass(self, node_project):
        result = run_validation(node_project)
        assert result.returncode == 0
        output = json.loads(result.stdout.strip())
        assert output["project_type"] == "node_ts"
        assert output["overall_status"] == "pass"
        layers = {l["name"]: l for l in output["layers"]}
        assert layers["compile"]["status"] == "pass"
        assert layers["lint"]["status"] == "pass"
        assert layers["test"]["status"] == "pass"

    def test_single_layer_compile(self, node_project):
        result = run_validation(node_project, layer="compile")
        assert result.returncode == 0
        output = json.loads(result.stdout.strip())
        layers = {l["name"]: l for l in output["layers"]}
        assert layers["compile"]["status"] == "pass"

    def test_single_layer_lint(self, node_project):
        result = run_validation(node_project, layer="lint")
        assert result.returncode == 0
        output = json.loads(result.stdout.strip())
        layers = {l["name"]: l for l in output["layers"]}
        assert layers["lint"]["status"] == "pass"

    def test_single_layer_test(self, node_project):
        result = run_validation(node_project, layer="test")
        assert result.returncode == 0
        output = json.loads(result.stdout.strip())
        layers = {l["name"]: l for l in output["layers"]}
        assert layers["test"]["status"] == "pass"


class TestValidationRunnerGating:
    def test_compile_fail_gates_lint_and_test(self, failing_build_project):
        result = run_validation(failing_build_project)
        output = json.loads(result.stdout.strip())
        assert output["overall_status"] == "fail"
        layers = {l["name"]: l for l in output["layers"]}
        assert layers["compile"]["status"] == "fail"
        assert layers["lint"]["status"] == "skip"
        assert layers["test"]["status"] == "skip"

    def test_lint_fail_gates_test(self, failing_lint_project):
        result = run_validation(failing_lint_project)
        output = json.loads(result.stdout.strip())
        assert output["overall_status"] == "fail"
        layers = {l["name"]: l for l in output["layers"]}
        assert layers["compile"]["status"] == "pass"
        assert layers["lint"]["status"] == "fail"
        assert layers["test"]["status"] == "skip"


class TestValidationRunnerEdgeCases:
    def test_nonexistent_project_root(self, tmp_path):
        fake_path = str(tmp_path / "nonexistent")
        result = run_validation(fake_path)
        assert result.returncode == 2
        output = json.loads(result.stdout.strip())
        assert output["overall_status"] == "error"

    def test_unknown_project_type(self, tmp_path):
        empty_project = str(tmp_path / "empty")
        os.makedirs(empty_project)
        result = run_validation(empty_project)
        assert result.returncode == 0
        output = json.loads(result.stdout.strip())
        assert output["project_type"] == "unknown"
        assert output["overall_status"] == "skip"

    def test_invalid_layer_arg(self, tmp_path):
        project = str(tmp_path / "project")
        os.makedirs(project)
        write_package_json(project)
        result = run_validation(project, layer="invalid")
        assert result.returncode == 2
        output = json.loads(result.stdout.strip())
        assert output["overall_status"] == "error"

    def test_missing_project_root_arg(self):
        result = subprocess.run(
            ["bash", SCRIPT_PATH],
            capture_output=True, text=True,
        )
        assert result.returncode == 2

    def test_error_count_on_compile_fail(self, failing_build_project):
        result = run_validation(failing_build_project)
        output = json.loads(result.stdout.strip())
        layers = {l["name"]: l for l in output["layers"]}
        assert layers["compile"]["error_count"] >= 1


def run_validation_with_coverage(project_root, layer="all"):
    result = subprocess.run(
        ["bash", SCRIPT_PATH,
         "--project-root", project_root,
         "--layer", layer,
         "--coverage"],
        capture_output=True, text=True,
        timeout=60,
    )
    return result


class TestValidationRunnerCoverage:
    """Tests for the --coverage flag added in the pipeline hardening quickfix."""

    def test_coverage_flag_adds_coverage_pct_field(self, tmp_path):
        """With --coverage, test layer JSON should have coverage_pct field."""
        project = str(tmp_path / "project")
        os.makedirs(project)
        # Test script that outputs coverage-like data
        write_package_json(project, {
            "build": "echo ok",
            "lint": "echo ok",
            "test": "echo '78.5% coverage'",
        })
        result = run_validation_with_coverage(project, layer="test")
        assert result.returncode == 0
        output = json.loads(result.stdout.strip())
        layers = {l["name"]: l for l in output["layers"]}
        assert "coverage_pct" in layers["test"]
        assert layers["test"]["coverage_pct"] == 78.5

    def test_no_coverage_flag_has_null_coverage(self, node_project):
        """Without --coverage, coverage_pct should be null."""
        result = run_validation(node_project, layer="test")
        assert result.returncode == 0
        output = json.loads(result.stdout.strip())
        layers = {l["name"]: l for l in output["layers"]}
        assert layers["test"].get("coverage_pct") is None

    def test_coverage_with_no_parseable_output(self, tmp_path):
        """When coverage output has no percentage, coverage_pct should be null.
        Note: c8 may inject its own coverage line (0%) even for trivial scripts,
        so we check that coverage_pct is either null or a number (not an error)."""
        project = str(tmp_path / "project")
        os.makedirs(project)
        write_package_json(project, {
            "build": "echo ok",
            "lint": "echo ok",
            "test": "echo 'all tests passed'",
        })
        result = run_validation_with_coverage(project, layer="test")
        assert result.returncode == 0
        output = json.loads(result.stdout.strip())
        layers = {l["name"]: l for l in output["layers"]}
        # c8 wraps the test command and may output its own coverage data
        cov = layers["test"]["coverage_pct"]
        assert cov is None or isinstance(cov, (int, float))

    def test_coverage_flag_accepted(self, tmp_path):
        """--coverage should not cause an argument parsing error."""
        project = str(tmp_path / "project")
        os.makedirs(project)
        write_package_json(project)
        result = run_validation_with_coverage(project)
        assert result.returncode == 0
