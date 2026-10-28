"""
Test skill: tdd-workflow
Verify that the Agent correctly implements a StringCalculator class using TDD
with comprehensive test coverage in the Python TDD starter project.
"""

import os
import subprocess
import sys
import ast
import inspect
import pytest


class TestTddWorkflow:
    REPO_DIR = "/workspace/python"

    # === File Path Checks ===

    def test_calculator_module_exists(self):
        """Verify that the calculator module file exists at the correct location"""
        filepath = os.path.join(self.REPO_DIR, "src/python_starter/calculator.py")
        assert os.path.exists(filepath), f"calculator.py not found at {filepath}"

    def test_test_calculator_file_exists(self):
        """Verify that the test file exists at the correct location"""
        filepath = os.path.join(self.REPO_DIR, "tests/test_calculator.py")
        assert os.path.exists(filepath), f"test_calculator.py not found at {filepath}"

    def test_calculator_module_is_valid_python(self):
        """Verify that calculator.py is valid Python syntax"""
        filepath = os.path.join(self.REPO_DIR, "src/python_starter/calculator.py")
        with open(filepath) as f:
            content = f.read()
        try:
            ast.parse(content)
        except SyntaxError as e:
            pytest.fail(f"calculator.py has syntax errors: {e}")

    def test_test_file_is_valid_python(self):
        """Verify that test_calculator.py is valid Python syntax"""
        filepath = os.path.join(self.REPO_DIR, "tests/test_calculator.py")
        with open(filepath) as f:
            content = f.read()
        try:
            ast.parse(content)
        except SyntaxError as e:
            pytest.fail(f"test_calculator.py has syntax errors: {e}")

    # === Semantic Checks ===

    def test_string_calculator_class_exists(self):
        """Verify that StringCalculator class is defined in calculator module"""
        sys.path.insert(0, os.path.join(self.REPO_DIR, "src"))
        try:
            from python_starter.calculator import StringCalculator
            assert inspect.isclass(StringCalculator), "StringCalculator must be a class"
        finally:
            sys.path.pop(0)

    def test_add_method_signature(self):
        """Verify that StringCalculator has an add method with correct signature"""
        sys.path.insert(0, os.path.join(self.REPO_DIR, "src"))
        try:
            from python_starter.calculator import StringCalculator
            assert hasattr(StringCalculator, 'add'), "StringCalculator missing 'add' method"
            sig = inspect.signature(StringCalculator.add)
            params = list(sig.parameters.keys())
            # Should have 'self' and 'numbers' (or similar)
            assert len(params) >= 2, (
                f"add() should take at least 2 parameters (self, numbers), got {params}"
            )
        finally:
            sys.path.pop(0)

    def test_test_file_has_at_least_15_test_cases(self):
        """Verify that test_calculator.py contains at least 15 distinct test functions"""
        filepath = os.path.join(self.REPO_DIR, "tests/test_calculator.py")
        with open(filepath) as f:
            content = f.read()
        tree = ast.parse(content)
        test_functions = []
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                if node.name.startswith("test_"):
                    test_functions.append(node.name)
        assert len(test_functions) >= 15, (
            f"Expected at least 15 test functions, found {len(test_functions)}: {test_functions}"
        )

    def test_test_file_covers_key_scenarios(self):
        """Verify that test file covers key scenarios: empty, negative, delimiter, large numbers"""
        filepath = os.path.join(self.REPO_DIR, "tests/test_calculator.py")
        with open(filepath) as f:
            content = f.read().lower()
        # Check for coverage of key scenarios by looking for relevant test patterns
        scenarios = {
            "empty": "empty" in content or '""' in content or "add(\"\")" in content,
            "negative": "negativ" in content or "ValueError" in content,
            "delimiter": "delimit" in content or "//" in content,
            "large_numbers": "1000" in content or "1001" in content or "large" in content,
        }
        missing = [s for s, found in scenarios.items() if not found]
        assert len(missing) == 0, (
            f"Test file missing coverage for scenarios: {missing}. "
            "Expected tests for empty input, negatives, custom delimiters, and large numbers."
        )

    # === Functional Checks ===

    def test_add_empty_string_returns_zero(self):
        """Verify that add('') returns 0"""
        sys.path.insert(0, os.path.join(self.REPO_DIR, "src"))
        try:
            from python_starter.calculator import StringCalculator
            calc = StringCalculator()
            result = calc.add("")
            assert result == 0, f"Expected add('') == 0, got {result}"
            assert isinstance(result, int), f"Expected int return type, got {type(result)}"
        finally:
            sys.path.pop(0)

    def test_add_single_number(self):
        """Verify that add('1') returns 1"""
        sys.path.insert(0, os.path.join(self.REPO_DIR, "src"))
        try:
            from python_starter.calculator import StringCalculator
            calc = StringCalculator()
            result = calc.add("1")
            assert result == 1, f"Expected add('1') == 1, got {result}"
        finally:
            sys.path.pop(0)

    def test_add_multiple_numbers(self):
        """Verify that add('1,2,3,4,5') returns 15"""
        sys.path.insert(0, os.path.join(self.REPO_DIR, "src"))
        try:
            from python_starter.calculator import StringCalculator
            calc = StringCalculator()
            result = calc.add("1,2,3,4,5")
            assert result == 15, f"Expected add('1,2,3,4,5') == 15, got {result}"
        finally:
            sys.path.pop(0)

    def test_add_with_newline_delimiter(self):
        """Verify that newline characters are valid delimiters"""
        sys.path.insert(0, os.path.join(self.REPO_DIR, "src"))
        try:
            from python_starter.calculator import StringCalculator
            calc = StringCalculator()
            result = calc.add("1\n2,3")
            assert result == 6, f"Expected add('1\\n2,3') == 6, got {result}"
        finally:
            sys.path.pop(0)

    def test_add_custom_delimiter(self):
        """Verify that custom single-character delimiter works"""
        sys.path.insert(0, os.path.join(self.REPO_DIR, "src"))
        try:
            from python_starter.calculator import StringCalculator
            calc = StringCalculator()
            result = calc.add("//;\n1;2")
            assert result == 3, f"Expected add('//;\\n1;2') == 3, got {result}"
        finally:
            sys.path.pop(0)

    def test_add_negative_numbers_raises_error(self):
        """Verify that negative numbers raise ValueError with all negatives listed"""
        sys.path.insert(0, os.path.join(self.REPO_DIR, "src"))
        try:
            from python_starter.calculator import StringCalculator
            calc = StringCalculator()
            with pytest.raises(ValueError) as exc_info:
                calc.add("-1,2,-3")
            error_msg = str(exc_info.value)
            assert "negatives not allowed" in error_msg.lower(), (
                f"Expected 'negatives not allowed' in error message, got: {error_msg}"
            )
            assert "-1" in error_msg, f"Expected -1 in error message, got: {error_msg}"
            assert "-3" in error_msg, f"Expected -3 in error message, got: {error_msg}"
        finally:
            sys.path.pop(0)

    def test_add_ignores_numbers_over_1000(self):
        """Verify that numbers > 1000 are excluded from the sum"""
        sys.path.insert(0, os.path.join(self.REPO_DIR, "src"))
        try:
            from python_starter.calculator import StringCalculator
            calc = StringCalculator()
            result = calc.add("2,1001")
            assert result == 2, f"Expected add('2,1001') == 2 (1001 ignored), got {result}"
            result2 = calc.add("1000,1001,6")
            assert result2 == 1006, f"Expected add('1000,1001,6') == 1006, got {result2}"
        finally:
            sys.path.pop(0)

    def test_add_multi_char_delimiter(self):
        """Verify that multi-character custom delimiters work"""
        sys.path.insert(0, os.path.join(self.REPO_DIR, "src"))
        try:
            from python_starter.calculator import StringCalculator
            calc = StringCalculator()
            result = calc.add("//[***]\n1***2***3")
            assert result == 6, f"Expected add('//[***]\\n1***2***3') == 6, got {result}"
        finally:
            sys.path.pop(0)

    def test_add_multiple_custom_delimiters(self):
        """Verify that multiple custom delimiters work simultaneously"""
        sys.path.insert(0, os.path.join(self.REPO_DIR, "src"))
        try:
            from python_starter.calculator import StringCalculator
            calc = StringCalculator()
            result = calc.add("//[*][%]\n1*2%3")
            assert result == 6, f"Expected add('//[*][%]\\n1*2%3') == 6, got {result}"
        finally:
            sys.path.pop(0)

    def test_existing_tests_pass(self):
        """Verify that all tests in test_calculator.py pass"""
        result = subprocess.run(
            ["python", "-m", "pytest", "tests/test_calculator.py", "-v", "--tb=short"],
            cwd=self.REPO_DIR,
            capture_output=True,
            text=True,
            timeout=120
        )
        assert result.returncode == 0, (
            f"Tests in test_calculator.py failed:\n{result.stdout[:3000]}\n{result.stderr[:1000]}"
        )
