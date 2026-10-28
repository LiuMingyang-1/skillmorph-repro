"""
Test skill: tdd-workflow
Verify that the StringCalculator class is correctly implemented using TDD,
including basic addition, custom delimiters, negative number rejection,
numbers > 1000 ignored, and comprehensive test coverage.
"""

import os
import sys
import ast
import inspect
import subprocess
import pytest


class TestTddWorkflow:
    REPO_DIR = "/workspace/python"

    # === File Path Checks ===

    def test_implementation_file_exists(self):
        """Verify that the StringCalculator implementation file exists"""
        filepath = os.path.join(self.REPO_DIR, "src/string_calculator.py")
        assert os.path.exists(filepath), \
            f"StringCalculator implementation not found at {filepath}"

    def test_test_file_exists(self):
        """Verify that the StringCalculator test file exists"""
        filepath = os.path.join(self.REPO_DIR, "tests/test_string_calculator.py")
        assert os.path.exists(filepath), \
            f"StringCalculator test file not found at {filepath}"

    def test_implementation_is_valid_python(self):
        """Verify that the implementation file parses as valid Python"""
        filepath = os.path.join(self.REPO_DIR, "src/string_calculator.py")
        with open(filepath) as f:
            content = f.read()
        try:
            ast.parse(content)
        except SyntaxError as e:
            pytest.fail(f"Syntax error in string_calculator.py: {e}")

    # === Semantic Checks ===

    def test_string_calculator_class_defined(self):
        """Verify that StringCalculator class exists with an 'add' method"""
        sys.path.insert(0, os.path.join(self.REPO_DIR, "src"))
        try:
            from string_calculator import StringCalculator
            assert hasattr(StringCalculator, 'add'), \
                "StringCalculator class is missing the 'add' method"
        finally:
            sys.path.pop(0)

    def test_add_method_signature(self):
        """Verify that add() accepts a string parameter and returns an int"""
        sys.path.insert(0, os.path.join(self.REPO_DIR, "src"))
        try:
            from string_calculator import StringCalculator
            sig = inspect.signature(StringCalculator.add)
            params = list(sig.parameters.keys())
            # Should have self (if instance method) and numbers
            assert len(params) >= 1, \
                f"add() should accept at least 1 parameter, got params: {params}"
        finally:
            sys.path.pop(0)

    def test_test_file_has_sufficient_test_cases(self):
        """Verify that the test suite has at least 8 test functions for TDD coverage"""
        filepath = os.path.join(self.REPO_DIR, "tests/test_string_calculator.py")
        with open(filepath) as f:
            content = f.read()
        test_count = len(re.findall(r'def\s+test_', content))
        assert test_count >= 8, \
            f"Expected at least 8 test cases for comprehensive TDD, found {test_count}"

    def test_test_file_covers_key_scenarios(self):
        """Verify that test file covers key scenarios: empty, negative, delimiter"""
        filepath = os.path.join(self.REPO_DIR, "tests/test_string_calculator.py")
        with open(filepath) as f:
            content = f.read().lower()
        # Check for evidence of key scenario coverage
        assert "empty" in content or '""' in content or "add(\"\")" in content, \
            "Test suite should cover empty string input"
        assert "negative" in content or "valueerror" in content or "raises" in content, \
            "Test suite should cover negative number handling"
        assert "delimiter" in content or "//" in content, \
            "Test suite should cover custom delimiter functionality"

    # === Functional Checks ===

    def test_add_empty_string_returns_zero(self):
        """Verify add('') returns 0"""
        sys.path.insert(0, os.path.join(self.REPO_DIR, "src"))
        try:
            from string_calculator import StringCalculator
            calc = StringCalculator()
            result = calc.add("")
            assert result == 0, f"Expected 0 for empty string, got {result}"
            assert isinstance(result, int), f"Return type should be int, got {type(result)}"
        finally:
            sys.path.pop(0)

    def test_add_single_number(self):
        """Verify add('5') returns 5"""
        sys.path.insert(0, os.path.join(self.REPO_DIR, "src"))
        try:
            from string_calculator import StringCalculator
            calc = StringCalculator()
            result = calc.add("5")
            assert result == 5, f"Expected 5 for input '5', got {result}"
        finally:
            sys.path.pop(0)

    def test_add_two_numbers(self):
        """Verify add('1,2') returns 3"""
        sys.path.insert(0, os.path.join(self.REPO_DIR, "src"))
        try:
            from string_calculator import StringCalculator
            calc = StringCalculator()
            result = calc.add("1,2")
            assert result == 3, f"Expected 3 for '1,2', got {result}"
        finally:
            sys.path.pop(0)

    def test_add_multiple_numbers(self):
        """Verify add('1,2,3') returns 6"""
        sys.path.insert(0, os.path.join(self.REPO_DIR, "src"))
        try:
            from string_calculator import StringCalculator
            calc = StringCalculator()
            result = calc.add("1,2,3")
            assert result == 6, f"Expected 6 for '1,2,3', got {result}"
        finally:
            sys.path.pop(0)

    def test_add_newline_delimiter(self):
        """Verify add('1\\n2,3') returns 6 with mixed newline and comma delimiters"""
        sys.path.insert(0, os.path.join(self.REPO_DIR, "src"))
        try:
            from string_calculator import StringCalculator
            calc = StringCalculator()
            result = calc.add("1\n2,3")
            assert result == 6, f"Expected 6 for '1\\n2,3', got {result}"
        finally:
            sys.path.pop(0)

    def test_add_custom_single_char_delimiter(self):
        """Verify add('//;\\n1;2;3') returns 6 with custom ';' delimiter"""
        sys.path.insert(0, os.path.join(self.REPO_DIR, "src"))
        try:
            from string_calculator import StringCalculator
            calc = StringCalculator()
            result = calc.add("//;\n1;2;3")
            assert result == 6, f"Expected 6 for '//;\\n1;2;3', got {result}"
        finally:
            sys.path.pop(0)

    def test_add_negative_numbers_raises_valueerror(self):
        """Verify that negative numbers raise ValueError listing all negatives"""
        sys.path.insert(0, os.path.join(self.REPO_DIR, "src"))
        try:
            from string_calculator import StringCalculator
            calc = StringCalculator()
            with pytest.raises(ValueError) as exc_info:
                calc.add("1,-2,3,-4")
            error_msg = str(exc_info.value)
            assert "-2" in error_msg, \
                f"ValueError message should include -2, got: {error_msg}"
            assert "-4" in error_msg, \
                f"ValueError message should include -4, got: {error_msg}"
        finally:
            sys.path.pop(0)

    def test_add_numbers_over_1000_ignored(self):
        """Verify that numbers greater than 1000 are excluded from sum"""
        sys.path.insert(0, os.path.join(self.REPO_DIR, "src"))
        try:
            from string_calculator import StringCalculator
            calc = StringCalculator()
            result = calc.add("2,1001")
            assert result == 2, \
                f"Expected 2 (1001 should be ignored), got {result}"
        finally:
            sys.path.pop(0)

    def test_add_boundary_1000_is_included(self):
        """Verify that exactly 1000 is included in the sum (only > 1000 is ignored)"""
        sys.path.insert(0, os.path.join(self.REPO_DIR, "src"))
        try:
            from string_calculator import StringCalculator
            calc = StringCalculator()
            result = calc.add("2,1000")
            assert result == 1002, \
                f"Expected 1002 (1000 should be included), got {result}"
        finally:
            sys.path.pop(0)

    def test_add_multi_char_delimiter(self):
        """Verify add('//[***]\\n1***2***3') returns 6 with multi-character delimiter"""
        sys.path.insert(0, os.path.join(self.REPO_DIR, "src"))
        try:
            from string_calculator import StringCalculator
            calc = StringCalculator()
            result = calc.add("//[***]\n1***2***3")
            assert result == 6, \
                f"Expected 6 for '//[***]\\n1***2***3', got {result}"
        finally:
            sys.path.pop(0)

    def test_add_multiple_delimiters(self):
        """Verify add('//[*][%]\\n1*2%3') returns 6 with multiple custom delimiters"""
        sys.path.insert(0, os.path.join(self.REPO_DIR, "src"))
        try:
            from string_calculator import StringCalculator
            calc = StringCalculator()
            result = calc.add("//[*][%]\n1*2%3")
            assert result == 6, \
                f"Expected 6 for '//[*][%]\\n1*2%3', got {result}"
        finally:
            sys.path.pop(0)

    def test_add_consecutive_delimiters_raises_error(self):
        """Verify that consecutive delimiters like '1,,2' raise ValueError"""
        sys.path.insert(0, os.path.join(self.REPO_DIR, "src"))
        try:
            from string_calculator import StringCalculator
            calc = StringCalculator()
            with pytest.raises(ValueError):
                calc.add("1,,2")
        finally:
            sys.path.pop(0)

    def test_agents_own_test_suite_passes(self):
        """Verify that the Agent's own test suite passes with pytest"""
        result = subprocess.run(
            ["python", "-m", "pytest", "tests/test_string_calculator.py", "-v", "--tb=short"],
            cwd=self.REPO_DIR,
            capture_output=True, text=True, timeout=120
        )
        assert result.returncode == 0, \
            f"Agent's own test suite failed:\n{result.stdout[-1500:]}\n{result.stderr[-500:]}"

    def test_custom_delimiter_empty_body_returns_zero(self):
        """Verify add('//;\\n') returns 0 when delimiter line has empty body"""
        sys.path.insert(0, os.path.join(self.REPO_DIR, "src"))
        try:
            from string_calculator import StringCalculator
            calc = StringCalculator()
            result = calc.add("//;\n")
            assert result == 0, \
                f"Expected 0 for '//;\\n' (empty body), got {result}"
        finally:
            sys.path.pop(0)


# Need re for semantic check
import re
