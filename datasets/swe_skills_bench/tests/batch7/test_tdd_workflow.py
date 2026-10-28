"""
Test skill: tdd-workflow
Verify that the Agent correctly implements a String Calculator
using test-driven development with full feature coverage.
"""

import os
import re
import sys
import subprocess
import pytest


class TestTddWorkflow:
    REPO_DIR = "/workspace/python"

    # === File Path Checks ===

    def test_calculator_module_exists(self):
        """Verify calculator.py exists in src/python_starter/"""
        fpath = os.path.join(self.REPO_DIR, "src/python_starter/calculator.py")
        assert os.path.isfile(fpath), f"calculator.py not found at {fpath}"

    def test_test_calculator_exists(self):
        """Verify test_calculator.py exists in tests/"""
        fpath = os.path.join(self.REPO_DIR, "tests/test_calculator.py")
        assert os.path.isfile(fpath), f"test_calculator.py not found at {fpath}"

    def test_calculator_module_is_parseable(self):
        """Verify calculator.py is valid Python"""
        import ast
        fpath = os.path.join(self.REPO_DIR, "src/python_starter/calculator.py")
        with open(fpath, "r") as f:
            source = f.read()
        try:
            ast.parse(source)
        except SyntaxError as e:
            pytest.fail(f"calculator.py has syntax error: {e}")

    # === Semantic Checks ===

    def test_add_function_exists_with_correct_signature(self):
        """Verify the add function exists and accepts a string parameter"""
        import ast
        fpath = os.path.join(self.REPO_DIR, "src/python_starter/calculator.py")
        with open(fpath, "r") as f:
            tree = ast.parse(f.read())
        func_names = [node.name for node in ast.walk(tree) if isinstance(node, ast.FunctionDef)]
        assert "add" in func_names, f"Function 'add' not found. Found: {func_names}"
        # Check the add function has at least one parameter (the numbers string)
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name == "add":
                params = [arg.arg for arg in node.args.args]
                assert len(params) >= 1, (
                    f"add() should take at least 1 parameter (numbers string), found params: {params}"
                )

    def test_test_file_has_sufficient_test_cases(self):
        """Verify test_calculator.py contains enough test functions"""
        import ast
        fpath = os.path.join(self.REPO_DIR, "tests/test_calculator.py")
        with open(fpath, "r") as f:
            tree = ast.parse(f.read())
        test_funcs = [
            node.name for node in ast.walk(tree)
            if isinstance(node, ast.FunctionDef) and node.name.startswith("test_")
        ]
        assert len(test_funcs) >= 5, (
            f"Expected at least 5 test functions, found {len(test_funcs)}: {test_funcs}"
        )

    def test_test_file_covers_negative_numbers(self):
        """Verify test_calculator.py has tests for negative number handling"""
        fpath = os.path.join(self.REPO_DIR, "tests/test_calculator.py")
        with open(fpath, "r") as f:
            content = f.read()
        has_negative_test = bool(re.search(r'(negative|ValueError|raises)', content))
        assert has_negative_test, "test_calculator.py should test negative number handling"

    def test_test_file_covers_custom_delimiters(self):
        """Verify test_calculator.py has tests for custom delimiter support"""
        fpath = os.path.join(self.REPO_DIR, "tests/test_calculator.py")
        with open(fpath, "r") as f:
            content = f.read()
        has_delimiter_test = bool(re.search(r'(delimiter|//|custom)', content, re.IGNORECASE))
        assert has_delimiter_test, "test_calculator.py should test custom delimiter support"

    # === Functional Checks ===

    def test_add_empty_string_returns_zero(self):
        """Verify add('') returns 0"""
        sys.path.insert(0, os.path.join(self.REPO_DIR, "src"))
        from python_starter.calculator import add
        result = add("")
        assert result == 0, f"add('') should return 0, got {result}"

    def test_add_single_number(self):
        """Verify add('1') returns 1"""
        sys.path.insert(0, os.path.join(self.REPO_DIR, "src"))
        from python_starter.calculator import add
        result = add("1")
        assert result == 1, f"add('1') should return 1, got {result}"

    def test_add_two_numbers_comma_separated(self):
        """Verify add('1,5') returns 6"""
        sys.path.insert(0, os.path.join(self.REPO_DIR, "src"))
        from python_starter.calculator import add
        result = add("1,5")
        assert result == 6, f"add('1,5') should return 6, got {result}"

    def test_add_multiple_numbers(self):
        """Verify add('1,2,3,4') returns 10"""
        sys.path.insert(0, os.path.join(self.REPO_DIR, "src"))
        from python_starter.calculator import add
        result = add("1,2,3,4")
        assert result == 10, f"add('1,2,3,4') should return 10, got {result}"

    def test_add_newline_delimiter(self):
        """Verify add('1\\n2,3') returns 6"""
        sys.path.insert(0, os.path.join(self.REPO_DIR, "src"))
        from python_starter.calculator import add
        result = add("1\n2,3")
        assert result == 6, f"add('1\\n2,3') should return 6, got {result}"

    def test_add_custom_delimiter(self):
        """Verify add('//;\\n1;2') with custom delimiter returns 3"""
        sys.path.insert(0, os.path.join(self.REPO_DIR, "src"))
        from python_starter.calculator import add
        result = add("//;\n1;2")
        assert result == 3, f"add('//;\\n1;2') should return 3, got {result}"

    def test_add_negative_numbers_raise_error(self):
        """Verify add with negative numbers raises ValueError listing all negatives"""
        sys.path.insert(0, os.path.join(self.REPO_DIR, "src"))
        from python_starter.calculator import add
        with pytest.raises(ValueError) as exc_info:
            add("1,-2,-3")
        error_msg = str(exc_info.value)
        assert "-2" in error_msg, f"Error message should contain '-2', got: {error_msg}"
        assert "-3" in error_msg, f"Error message should contain '-3', got: {error_msg}"

    def test_add_numbers_over_1000_ignored(self):
        """Verify numbers greater than 1000 are ignored"""
        sys.path.insert(0, os.path.join(self.REPO_DIR, "src"))
        from python_starter.calculator import add
        result = add("2,1001")
        assert result == 2, f"add('2,1001') should return 2, got {result}"
        result2 = add("1000,1001,6")
        assert result2 == 1006, f"add('1000,1001,6') should return 1006, got {result2}"

    def test_add_multi_char_delimiter(self):
        """Verify add('//[***]\\n1***2***3') with multi-char delimiter returns 6"""
        sys.path.insert(0, os.path.join(self.REPO_DIR, "src"))
        from python_starter.calculator import add
        result = add("//[***]\n1***2***3")
        assert result == 6, f"add('//[***]\\n1***2***3') should return 6, got {result}"

    def test_add_multiple_delimiters(self):
        """Verify add('//[*][%]\\n1*2%3') with multiple delimiters returns 6"""
        sys.path.insert(0, os.path.join(self.REPO_DIR, "src"))
        from python_starter.calculator import add
        result = add("//[*][%]\n1*2%3")
        assert result == 6, f"add('//[*][%]\\n1*2%3') should return 6, got {result}"

    def test_project_tests_pass(self):
        """Verify all project tests pass via pytest"""
        result = subprocess.run(
            ["python", "-m", "pytest", "tests/", "-v", "--tb=short"],
            cwd=self.REPO_DIR,
            capture_output=True,
            text=True,
            timeout=120
        )
        assert result.returncode == 0, f"Project tests failed:\n{result.stdout[-1000:]}\n{result.stderr[-500:]}"
        # Verify at least some tests ran
        passed_match = re.search(r'(\d+) passed', result.stdout)
        assert passed_match, "Could not find pass count in pytest output"
        passed_count = int(passed_match.group(1))
        assert passed_count >= 5, f"Expected at least 5 tests to pass, got {passed_count}"
