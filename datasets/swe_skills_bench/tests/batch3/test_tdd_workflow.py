"""
Test skill: tdd-workflow
Verify that the Agent correctly implements a StringCalculator using TDD in a Python project.
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
        """Verify that the StringCalculator source file exists"""
        calc_path = os.path.join(self.REPO_DIR, "src/string_calculator.py")
        assert os.path.exists(calc_path), f"string_calculator.py not found at {calc_path}"

    def test_string_calculator_is_valid_python(self):
        """Verify that string_calculator.py is valid Python"""
        calc_path = os.path.join(self.REPO_DIR, "src/string_calculator.py")
        with open(calc_path) as f:
            source = f.read()
        ast.parse(source)

    def test_test_file_exists(self):
        """Verify that the test file for StringCalculator exists"""
        test_path = os.path.join(self.REPO_DIR, "tests/test_string_calculator.py")
        assert os.path.exists(test_path), \
            f"test_string_calculator.py not found at {test_path}"
        with open(test_path) as f:
            ast.parse(f.read())

    # === Semantic Checks ===

    def test_string_calculator_class_exists(self):
        """Verify that StringCalculator class is defined with an add method"""
        sys.path.insert(0, os.path.join(self.REPO_DIR, "src"))
        try:
            from string_calculator import StringCalculator
            assert hasattr(StringCalculator, "add"), \
                "StringCalculator missing 'add' method"
            import inspect
            sig = inspect.signature(StringCalculator.add)
            params = list(sig.parameters.keys())
            # Should accept self (or cls) and a numbers string
            assert len(params) >= 1, \
                f"add method should accept at least one parameter (numbers), got {params}"
        finally:
            sys.path.pop(0)
            for mod_name in list(sys.modules.keys()):
                if "string_calculator" in mod_name:
                    del sys.modules[mod_name]

    def test_test_file_has_sufficient_test_cases(self):
        """Verify the test file contains a reasonable number of test functions"""
        test_path = os.path.join(self.REPO_DIR, "tests/test_string_calculator.py")
        with open(test_path) as f:
            tree = ast.parse(f.read())
        test_funcs = [
            node for node in ast.walk(tree)
            if isinstance(node, ast.FunctionDef) and node.name.startswith("test_")
        ]
        assert len(test_funcs) >= 5, \
            f"Test file should have at least 5 test functions, found {len(test_funcs)}"

    def test_test_file_covers_valueerror(self):
        """Verify that test file includes tests for ValueError (negatives, invalid input)"""
        test_path = os.path.join(self.REPO_DIR, "tests/test_string_calculator.py")
        with open(test_path) as f:
            content = f.read()
        assert "ValueError" in content, \
            "Test file should test ValueError for negative numbers or invalid input"

    # === Functional Checks ===

    def _get_calculator(self):
        """Helper: import and return StringCalculator instance"""
        sys.path.insert(0, os.path.join(self.REPO_DIR, "src"))
        from string_calculator import StringCalculator
        return StringCalculator()

    def _cleanup_imports(self):
        """Helper: clean up sys.path and module cache"""
        src_path = os.path.join(self.REPO_DIR, "src")
        if src_path in sys.path:
            sys.path.remove(src_path)
        for mod_name in list(sys.modules.keys()):
            if "string_calculator" in mod_name:
                del sys.modules[mod_name]

    def test_add_empty_string_returns_zero(self):
        """Verify add('') returns 0"""
        try:
            calc = self._get_calculator()
            result = calc.add("")
            assert result == 0, f"add('') should return 0, got {result}"
        finally:
            self._cleanup_imports()

    def test_add_single_number(self):
        """Verify add('1') returns 1"""
        try:
            calc = self._get_calculator()
            result = calc.add("1")
            assert result == 1, f"add('1') should return 1, got {result}"
        finally:
            self._cleanup_imports()

    def test_add_two_numbers(self):
        """Verify add('1,2') returns 3"""
        try:
            calc = self._get_calculator()
            result = calc.add("1,2")
            assert result == 3, f"add('1,2') should return 3, got {result}"
        finally:
            self._cleanup_imports()

    def test_add_multiple_numbers(self):
        """Verify add handles any number of values: add('1,2,3,4,5') returns 15"""
        try:
            calc = self._get_calculator()
            result = calc.add("1,2,3,4,5")
            assert result == 15, f"add('1,2,3,4,5') should return 15, got {result}"
        finally:
            self._cleanup_imports()

    def test_add_newline_delimiter(self):
        """Verify newlines work as delimiters: add('1\\n2,3') returns 6"""
        try:
            calc = self._get_calculator()
            result = calc.add("1\n2,3")
            assert result == 6, f"add('1\\n2,3') should return 6, got {result}"
        finally:
            self._cleanup_imports()

    def test_add_custom_delimiter(self):
        """Verify custom single-char delimiter: add('//;\\n1;2') returns 3"""
        try:
            calc = self._get_calculator()
            result = calc.add("//;\n1;2")
            assert result == 3, f"add('//;\\n1;2') should return 3, got {result}"
        finally:
            self._cleanup_imports()

    def test_add_custom_pipe_delimiter(self):
        """Verify custom pipe delimiter: add('//|\\n4|5|6') returns 15"""
        try:
            calc = self._get_calculator()
            result = calc.add("//|\n4|5|6")
            assert result == 15, f"add('//|\\n4|5|6') should return 15, got {result}"
        finally:
            self._cleanup_imports()

    def test_add_multi_char_delimiter(self):
        """Verify multi-char delimiter: add('//[***]\\n1***2***3') returns 6"""
        try:
            calc = self._get_calculator()
            result = calc.add("//[***]\n1***2***3")
            assert result == 6, f"add('//[***]\\n1***2***3') should return 6, got {result}"
        finally:
            self._cleanup_imports()

    def test_add_multiple_delimiters(self):
        """Verify multiple delimiters: add('//[*][%]\\n1*2%3') returns 6"""
        try:
            calc = self._get_calculator()
            result = calc.add("//[*][%]\n1*2%3")
            assert result == 6, f"add('//[*][%]\\n1*2%3') should return 6, got {result}"
        finally:
            self._cleanup_imports()

    def test_add_negative_numbers_raises_valueerror(self):
        """Verify negative numbers raise ValueError listing all negatives"""
        try:
            calc = self._get_calculator()
            with pytest.raises(ValueError) as exc_info:
                calc.add("-1,2,-3")
            msg = str(exc_info.value)
            assert "-1" in msg, f"Error message should mention -1: {msg}"
            assert "-3" in msg, f"Error message should mention -3: {msg}"
            assert "negativ" in msg.lower() or "not allowed" in msg.lower(), \
                f"Error message should mention negatives not allowed: {msg}"
        finally:
            self._cleanup_imports()

    def test_add_numbers_greater_than_1000_ignored(self):
        """Verify numbers > 1000 are ignored: add('2,1001') returns 2"""
        try:
            calc = self._get_calculator()
            result = calc.add("2,1001")
            assert result == 2, f"add('2,1001') should return 2, got {result}"
        finally:
            self._cleanup_imports()

    def test_add_number_exactly_1000_included(self):
        """Verify 1000 is included: add('1000,2') returns 1002"""
        try:
            calc = self._get_calculator()
            result = calc.add("1000,2")
            assert result == 1002, f"add('1000,2') should return 1002, got {result}"
        finally:
            self._cleanup_imports()

    def test_add_trailing_delimiter_raises_valueerror(self):
        """Verify trailing delimiter raises ValueError: add('1,\\n')"""
        try:
            calc = self._get_calculator()
            with pytest.raises(ValueError) as exc_info:
                calc.add("1,\n")
            msg = str(exc_info.value).lower()
            assert "trailing" in msg or "invalid" in msg, \
                f"Error should mention trailing or invalid input: {exc_info.value}"
        finally:
            self._cleanup_imports()

    def test_agent_tests_pass(self):
        """Verify the Agent's own test suite passes"""
        test_path = os.path.join(self.REPO_DIR, "tests/test_string_calculator.py")
        if not os.path.exists(test_path):
            pytest.skip("Agent's test file not found")
        result = subprocess.run(
            ["python", "-m", "pytest", test_path, "-v", "--tb=short"],
            cwd=self.REPO_DIR,
            capture_output=True, text=True, timeout=120
        )
        assert result.returncode == 0, \
            f"Agent's test suite failed:\n{result.stdout[:2000]}\n{result.stderr[:500]}"
