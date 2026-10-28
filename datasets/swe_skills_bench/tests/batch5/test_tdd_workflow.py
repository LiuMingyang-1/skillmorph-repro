"""
Test skill: tdd-workflow
Verify that the Agent correctly implements a StringCalculator class
following TDD methodology with full feature coverage.
"""

import os
import sys
import ast
import subprocess
import pytest


class TestTddWorkflow:
    REPO_DIR = "/workspace/python"

    # === File Path Checks ===

    def test_string_calculator_file_exists(self):
        """Verify src/string_calculator.py exists"""
        filepath = os.path.join(self.REPO_DIR, "src/string_calculator.py")
        assert os.path.exists(filepath), \
            f"string_calculator.py not found at {filepath}"

    def test_test_file_exists(self):
        """Verify tests/test_string_calculator.py exists"""
        filepath = os.path.join(self.REPO_DIR, "tests/test_string_calculator.py")
        assert os.path.exists(filepath), \
            f"test_string_calculator.py not found at {filepath}"

    def test_source_file_is_valid_python(self):
        """Verify string_calculator.py is valid Python syntax"""
        filepath = os.path.join(self.REPO_DIR, "src/string_calculator.py")
        with open(filepath) as f:
            source = f.read()
        try:
            ast.parse(source)
        except SyntaxError as e:
            pytest.fail(f"string_calculator.py has syntax error: {e}")

    # === Semantic Checks ===

    def test_string_calculator_class_exists(self):
        """Verify StringCalculator class is defined"""
        filepath = os.path.join(self.REPO_DIR, "src/string_calculator.py")
        with open(filepath) as f:
            tree = ast.parse(f.read())
        classes = [
            node.name for node in ast.walk(tree)
            if isinstance(node, ast.ClassDef)
        ]
        assert "StringCalculator" in classes, \
            f"StringCalculator class not found. Classes defined: {classes}"

    def test_add_method_exists(self):
        """Verify StringCalculator has an 'add' method"""
        sys.path.insert(0, os.path.join(self.REPO_DIR, "src"))
        try:
            from string_calculator import StringCalculator
            calc = StringCalculator()
            assert hasattr(calc, 'add'), "StringCalculator missing 'add' method"
            assert callable(calc.add), "'add' is not callable"
        finally:
            sys.path.pop(0)

    def test_add_method_takes_string_argument(self):
        """Verify the add method accepts a string parameter"""
        import inspect
        sys.path.insert(0, os.path.join(self.REPO_DIR, "src"))
        try:
            from string_calculator import StringCalculator
            sig = inspect.signature(StringCalculator.add)
            params = list(sig.parameters.keys())
            # Should have self + at least one parameter (numbers)
            assert len(params) >= 2, \
                f"add() should take at least 1 argument besides self, has params: {params}"
        finally:
            sys.path.pop(0)

    def test_test_file_has_at_least_10_tests(self):
        """Verify the test file contains at least 10 test functions"""
        filepath = os.path.join(self.REPO_DIR, "tests/test_string_calculator.py")
        with open(filepath) as f:
            tree = ast.parse(f.read())
        test_funcs = [
            node.name for node in ast.walk(tree)
            if isinstance(node, ast.FunctionDef) and node.name.startswith("test_")
        ]
        assert len(test_funcs) >= 10, \
            f"Expected at least 10 test functions, found {len(test_funcs)}: {test_funcs}"

    # === Functional Checks ===

    def _get_calculator(self):
        """Helper to import and return a StringCalculator instance."""
        sys.path.insert(0, os.path.join(self.REPO_DIR, "src"))
        from string_calculator import StringCalculator
        return StringCalculator()

    def test_empty_string_returns_zero(self):
        """Verify add('') returns 0"""
        calc = self._get_calculator()
        result = calc.add("")
        assert result == 0, f"add('') should return 0, got {result}"
        assert isinstance(result, int), f"Return type should be int, got {type(result)}"

    def test_single_number(self):
        """Verify add('42') returns 42"""
        calc = self._get_calculator()
        assert calc.add("1") == 1, "add('1') should return 1"
        assert calc.add("42") == 42, "add('42') should return 42"

    def test_two_numbers_comma_delimited(self):
        """Verify add('1,2') returns 3"""
        calc = self._get_calculator()
        result = calc.add("1,2")
        assert result == 3, f"add('1,2') should return 3, got {result}"

    def test_multiple_numbers(self):
        """Verify add handles multiple comma-delimited numbers"""
        calc = self._get_calculator()
        result = calc.add("1,2,3,4,5")
        assert result == 15, f"add('1,2,3,4,5') should return 15, got {result}"

    def test_newline_delimiter(self):
        """Verify newline works as delimiter alongside comma"""
        calc = self._get_calculator()
        result = calc.add("1\n2,3")
        assert result == 6, f"add('1\\n2,3') should return 6, got {result}"

    def test_custom_delimiter(self):
        """Verify custom single-char delimiter via //[delim]\\n format"""
        calc = self._get_calculator()
        result = calc.add("//;\n1;2;3")
        assert result == 6, f"add('//;\\n1;2;3') should return 6, got {result}"
        result2 = calc.add("//|\n4|5|6")
        assert result2 == 15, f"add('//|\\n4|5|6') should return 15, got {result2}"

    def test_negative_numbers_raise_error(self):
        """Verify add raises ValueError with all negatives listed when negatives present"""
        calc = self._get_calculator()
        with pytest.raises(ValueError) as exc_info:
            calc.add("1,-2,3,-4")
        msg = str(exc_info.value)
        assert "-2" in msg, f"Error message should mention -2: {msg}"
        assert "-4" in msg, f"Error message should mention -4: {msg}"

    def test_numbers_greater_than_1000_ignored(self):
        """Verify numbers > 1000 are ignored; 1000 is included"""
        calc = self._get_calculator()
        assert calc.add("2,1001") == 2, "add('2,1001') should return 2 (1001 ignored)"
        assert calc.add("1000,1001,999") == 1999, \
            "add('1000,1001,999') should return 1999 (1000 included, 1001 ignored)"

    def test_multi_char_custom_delimiter(self):
        """Verify multi-character custom delimiter via //[delim]\\n format"""
        calc = self._get_calculator()
        result = calc.add("//[***]\n1***2***3")
        assert result == 6, f"add('//[***]\\n1***2***3') should return 6, got {result}"

    def test_multiple_custom_delimiters(self):
        """Verify multiple custom delimiters via //[d1][d2]\\n format"""
        calc = self._get_calculator()
        result = calc.add("//[*][%]\n1*2%3")
        assert result == 6, f"add('//[*][%]\\n1*2%3') should return 6, got {result}"
        result2 = calc.add("//[**][%%]\n1**2%%3")
        assert result2 == 6, f"add('//[**][%%]\\n1**2%%3') should return 6, got {result2}"

    def test_existing_tests_pass(self):
        """Verify all tests in the project pass with pytest"""
        result = subprocess.run(
            ["python", "-m", "pytest", "tests/test_string_calculator.py", "-v"],
            cwd=self.REPO_DIR,
            capture_output=True,
            text=True,
            timeout=120,
        )
        assert result.returncode == 0, \
            f"Project tests failed:\n{result.stdout[-500:]}\n{result.stderr[-500:]}"
