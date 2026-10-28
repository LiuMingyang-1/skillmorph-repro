"""
Test skill: tdd-workflow
Verify that the Agent correctly implements parenthesized expressions, modulo operator,
and unary negation in the calculator's evaluate() function following TDD.
"""

import os
import subprocess
import ast
import re
import pytest


class TestTddWorkflow:
    REPO_DIR = "/workspace/python"

    # === File Path Checks ===

    def test_calculator_module_exists(self):
        """Verify calculator.py exists"""
        path = os.path.join(self.REPO_DIR, "src/python_starter/calculator.py")
        assert os.path.exists(path), f"calculator.py not found at {path}"

    def test_test_calculator_exists(self):
        """Verify test_calculator.py exists"""
        path = os.path.join(self.REPO_DIR, "tests/test_calculator.py")
        assert os.path.exists(path), f"test_calculator.py not found at {path}"

    # === Semantic Checks ===

    def test_calculator_has_evaluate_function(self):
        """Verify calculator module defines evaluate function"""
        path = os.path.join(self.REPO_DIR, "src/python_starter/calculator.py")
        with open(path) as f:
            source = f.read()
        tree = ast.parse(source)
        func_names = [
            node.name for node in ast.walk(tree)
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        ]
        assert "evaluate" in func_names, (
            f"evaluate function not found. Functions defined: {func_names}"
        )

    def test_calculator_handles_parentheses(self):
        """Verify calculator source contains logic for handling parentheses"""
        path = os.path.join(self.REPO_DIR, "src/python_starter/calculator.py")
        with open(path) as f:
            source = f.read()
        has_paren = ("(" in source and ")" in source) and (
            "paren" in source.lower()
            or re.search(r"['\"][\(]", source)
            or "group" in source.lower()
            or re.search(r"token.*\(", source)
        )
        assert has_paren, "Calculator source does not appear to handle parenthesized expressions"

    def test_calculator_handles_modulo(self):
        """Verify calculator source contains logic for modulo operator"""
        path = os.path.join(self.REPO_DIR, "src/python_starter/calculator.py")
        with open(path) as f:
            source = f.read()
        has_modulo = "%" in source or "mod" in source.lower()
        assert has_modulo, "Calculator source does not appear to handle modulo operator"

    def test_calculator_handles_unary_negation(self):
        """Verify calculator source contains logic for unary negation"""
        path = os.path.join(self.REPO_DIR, "src/python_starter/calculator.py")
        with open(path) as f:
            source = f.read()
        has_negation = (
            "unary" in source.lower()
            or "negate" in source.lower()
            or re.search(r"[-].*prefix", source, re.IGNORECASE)
            or re.search(r"token.*==.*'-'", source)
            or "negative" in source.lower()
        )
        assert has_negation, "Calculator source does not appear to handle unary negation"

    def test_test_file_covers_parentheses(self):
        """Verify test file includes tests for parenthesized expressions"""
        path = os.path.join(self.REPO_DIR, "tests/test_calculator.py")
        with open(path) as f:
            source = f.read()
        has_paren_test = (
            "(" in source
            and re.search(r"['\"].*\(.*\).*['\"]", source)
        )
        assert has_paren_test, "Test file does not contain tests with parenthesized expressions"

    def test_test_file_covers_modulo(self):
        """Verify test file includes tests for modulo operator"""
        path = os.path.join(self.REPO_DIR, "tests/test_calculator.py")
        with open(path) as f:
            source = f.read()
        has_modulo_test = "%" in source
        assert has_modulo_test, "Test file does not contain tests for modulo operator"

    # === Functional Checks ===

    def test_evaluate_parentheses_basic(self):
        """Verify evaluate('(2 + 3) * 4') returns 20"""
        result = subprocess.run(
            [
                "python", "-c",
                "import sys; sys.path.insert(0, 'src'); "
                "from python_starter.calculator import evaluate; "
                "r = evaluate('(2 + 3) * 4'); "
                "assert r == 20, f'Expected 20 got {r}'; print('PASS')"
            ],
            cwd=self.REPO_DIR,
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert result.returncode == 0, f"Parentheses test failed: {result.stderr}"
        assert "PASS" in result.stdout

    def test_evaluate_modulo_basic(self):
        """Verify evaluate('10 % 3') returns 1"""
        result = subprocess.run(
            [
                "python", "-c",
                "import sys; sys.path.insert(0, 'src'); "
                "from python_starter.calculator import evaluate; "
                "r = evaluate('10 % 3'); "
                "assert r == 1, f'Expected 1 got {r}'; print('PASS')"
            ],
            cwd=self.REPO_DIR,
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert result.returncode == 0, f"Modulo test failed: {result.stderr}"
        assert "PASS" in result.stdout

    def test_evaluate_unary_negation(self):
        """Verify evaluate('-5 + 3') returns -2"""
        result = subprocess.run(
            [
                "python", "-c",
                "import sys; sys.path.insert(0, 'src'); "
                "from python_starter.calculator import evaluate; "
                "r = evaluate('-5 + 3'); "
                "assert r == -2, f'Expected -2 got {r}'; print('PASS')"
            ],
            cwd=self.REPO_DIR,
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert result.returncode == 0, f"Unary negation test failed: {result.stderr}"
        assert "PASS" in result.stdout

    def test_evaluate_nested_parentheses(self):
        """Verify evaluate('((2 + 3) * (4 - 1))') returns 15"""
        result = subprocess.run(
            [
                "python", "-c",
                "import sys; sys.path.insert(0, 'src'); "
                "from python_starter.calculator import evaluate; "
                "r = evaluate('((2 + 3) * (4 - 1))'); "
                "assert r == 15, f'Expected 15 got {r}'; print('PASS')"
            ],
            cwd=self.REPO_DIR,
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert result.returncode == 0, f"Nested parens failed: {result.stderr}"
        assert "PASS" in result.stdout

    def test_all_existing_tests_pass(self):
        """Verify all tests pass via pytest"""
        result = subprocess.run(
            ["python", "-m", "pytest", "tests/", "-v"],
            cwd=self.REPO_DIR,
            capture_output=True,
            text=True,
            timeout=120,
        )
        assert result.returncode == 0, (
            f"Some tests failed:\n{result.stdout[-1000:]}\n{result.stderr[:500]}"
        )
