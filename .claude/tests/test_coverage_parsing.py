"""Unit tests for merge-gate.py pure functions: classify_failure, truncate_output, parse_coverage_pct."""
import os
from importlib.util import spec_from_file_location, module_from_spec

SCRIPT_PATH = os.path.join(os.path.dirname(__file__), "..", "..", "scripts", "merge-gate.py")
spec = spec_from_file_location("merge_gate", SCRIPT_PATH)
mg = module_from_spec(spec)
spec.loader.exec_module(mg)

classify_failure = mg.classify_failure
truncate_output = mg.truncate_output
parse_coverage_pct = mg.parse_coverage_pct


class TestClassifyFailure:
    def test_compile_error_cannot_find_module(self):
        assert classify_failure("Cannot find module 'foo'") == "compile_error"

    def test_compile_error_is_not_a_function(self):
        assert classify_failure("foo.bar is not a function") == "compile_error"

    def test_compile_error_no_exported_member(self):
        assert classify_failure("Module 'x' has no exported member 'y'") == "compile_error"

    def test_compile_error_import_error(self):
        assert classify_failure("ImportError: No module named 'z'") == "compile_error"

    def test_compile_error_module_not_found(self):
        assert classify_failure("ModuleNotFoundError: No module named 'abc'") == "compile_error"

    def test_compile_error_undefined_is_not(self):
        assert classify_failure("undefined is not an object") == "compile_error"

    def test_compile_error_type_error(self):
        assert classify_failure("TypeError: x is not callable") == "compile_error"

    def test_compile_error_syntax_error(self):
        assert classify_failure("SyntaxError: Unexpected token") == "compile_error"

    def test_logic_failure_assertion_error(self):
        assert classify_failure("AssertionError: expected 1 to equal 2") == "logic_failure"

    def test_logic_failure_expected_to_equal(self):
        assert classify_failure("Expected 'foo' to equal 'bar'") == "logic_failure"

    def test_logic_failure_expected_but_got(self):
        assert classify_failure("expected true but got false") == "logic_failure"

    def test_logic_failure_fail_assert(self):
        assert classify_failure("FAIL: assert x == y") == "logic_failure"

    def test_logic_failure_timeout_error(self):
        assert classify_failure("TimeoutError: test timed out") == "logic_failure"

    def test_logic_failure_timed_out(self):
        assert classify_failure("timed out after 300 seconds") == "logic_failure"

    def test_ambiguous_no_patterns(self):
        assert classify_failure("RuntimeError: something went wrong") == "ambiguous"

    def test_ambiguous_empty_string(self):
        assert classify_failure("") == "ambiguous"

    def test_compile_takes_priority_over_logic(self):
        output = "TypeError: x is not callable\nAssertionError: expected true"
        assert classify_failure(output) == "compile_error"


class TestTruncateOutput:
    def test_none_returns_none(self):
        assert truncate_output(None) is None

    def test_empty_returns_none(self):
        assert truncate_output("") is None

    def test_short_text_unchanged(self):
        text = "line 1\nline 2\nline 3"
        assert truncate_output(text) == text

    def test_exactly_50_lines_unchanged(self):
        lines = [f"line {i}" for i in range(50)]
        text = "\n".join(lines)
        assert truncate_output(text) == text

    def test_51_lines_truncated_to_last_50(self):
        lines = [f"line {i}" for i in range(51)]
        text = "\n".join(lines)
        result = truncate_output(text)
        result_lines = result.splitlines()
        assert len(result_lines) == 50
        assert result_lines[0] == "line 1"
        assert result_lines[-1] == "line 50"

    def test_custom_max_lines(self):
        lines = [f"line {i}" for i in range(20)]
        text = "\n".join(lines)
        result = truncate_output(text, max_lines=5)
        result_lines = result.splitlines()
        assert len(result_lines) == 5
        assert result_lines[0] == "line 15"
        assert result_lines[-1] == "line 19"


class TestParseCoveragePct:
    """Test coverage percentage parsing against real tool output formats."""

    def test_nyc_c8_all_files(self):
        output = "All files  |   78.5  |    72.3  |    85.1  |    76.2  |"
        assert parse_coverage_pct(output) == 78.5

    def test_pytest_cov_total(self):
        output = "TOTAL                        500    400    80%"
        assert parse_coverage_pct(output) == 80.0

    def test_go_coverage(self):
        output = "coverage: 65.2% of statements"
        assert parse_coverage_pct(output) == 65.2

    def test_istanbul_statements(self):
        output = "Statements   : 85.71% ( 120/140 )"
        assert parse_coverage_pct(output) == 85.71

    def test_generic_pct_coverage(self):
        output = "78.5% coverage"
        assert parse_coverage_pct(output) == 78.5

    def test_zero_percent(self):
        output = "0.0% coverage"
        assert parse_coverage_pct(output) == 0.0

    def test_hundred_percent(self):
        output = "100% coverage"
        assert parse_coverage_pct(output) == 100.0

    def test_no_match_returns_none(self):
        assert parse_coverage_pct("no coverage data here") is None

    def test_empty_string_returns_none(self):
        assert parse_coverage_pct("") is None

    def test_multiline_output_last_match(self):
        output = "file1.py   50%\nfile2.py   60%\nTOTAL 100 75 75%"
        result = parse_coverage_pct(output)
        assert result is not None
        # Should match TOTAL line pattern first (75%)
        assert result == 75.0

    def test_flutter_coverage_format(self):
        output = "72.1% coverage of package:my_app"
        assert parse_coverage_pct(output) == 72.1
