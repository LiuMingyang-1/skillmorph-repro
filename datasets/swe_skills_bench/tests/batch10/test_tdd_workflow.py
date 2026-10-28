"""
Test skill: tdd-workflow
Verify that the Agent correctly implements a PasswordValidator class using
Test-Driven Development in the tdd-starters/python repository.
"""

import os
import sys
import subprocess
import pytest


class TestTddWorkflow:
    REPO_DIR = "/workspace/python"

    # === File Path Checks ===

    def test_password_validator_module_exists(self):
        """Verify that password_validator.py was created at the correct location"""
        path = os.path.join(self.REPO_DIR, "src/python_starter/password_validator.py")
        assert os.path.exists(path), f"password_validator.py not found at {path}"

    def test_password_validator_module_is_valid_python(self):
        """Verify that password_validator.py is syntactically valid Python"""
        import ast
        path = os.path.join(self.REPO_DIR, "src/python_starter/password_validator.py")
        with open(path) as f:
            source = f.read()
        try:
            ast.parse(source)
        except SyntaxError as e:
            pytest.fail(f"password_validator.py has syntax errors: {e}")

    def test_test_file_exists(self):
        """Verify that the test file was created"""
        path = os.path.join(self.REPO_DIR, "tests/test_password_validator.py")
        assert os.path.exists(path), f"Test file not found at {path}"

    # === Semantic Checks ===

    def test_password_validator_class_exists(self):
        """Verify that the PasswordValidator class is defined and importable"""
        sys.path.insert(0, self.REPO_DIR)
        try:
            from src.python_starter.password_validator import PasswordValidator
            assert PasswordValidator is not None, "PasswordValidator class is None"
        finally:
            sys.path.pop(0)

    def test_validate_method_exists_with_correct_signature(self):
        """Verify that PasswordValidator has a validate method accepting a password string"""
        import inspect
        sys.path.insert(0, self.REPO_DIR)
        try:
            from src.python_starter.password_validator import PasswordValidator
            assert hasattr(PasswordValidator, 'validate'), "PasswordValidator missing 'validate' method"
            sig = inspect.signature(PasswordValidator.validate)
            params = list(sig.parameters.keys())
            # Should have self + password (or just password if static)
            assert len(params) >= 1, (
                f"validate() should accept at least a password parameter, got params: {params}"
            )
        finally:
            sys.path.pop(0)

    def test_validate_returns_dict_with_required_keys(self):
        """Verify that validate returns a dict with 'valid', 'score', and 'errors' keys"""
        sys.path.insert(0, self.REPO_DIR)
        try:
            from src.python_starter.password_validator import PasswordValidator
            validator = PasswordValidator()
            result = validator.validate("Str0ng!Pass")
            assert isinstance(result, dict), f"validate() should return dict, got {type(result)}"
            assert "valid" in result, "Result missing 'valid' key"
            assert "score" in result, "Result missing 'score' key"
            assert "errors" in result, "Result missing 'errors' key"
            assert isinstance(result["valid"], bool), f"'valid' should be bool, got {type(result['valid'])}"
            assert isinstance(result["score"], int), f"'score' should be int, got {type(result['score'])}"
            assert isinstance(result["errors"], list), f"'errors' should be list, got {type(result['errors'])}"
        finally:
            sys.path.pop(0)

    def test_score_range_is_zero_to_five(self):
        """Verify that score is always between 0 and 5 inclusive"""
        sys.path.insert(0, self.REPO_DIR)
        try:
            from src.python_starter.password_validator import PasswordValidator
            validator = PasswordValidator()
            # Test with various inputs
            for pwd in ["", "a", "Str0ng!Pass", "abcdefgh", "ABCDEFGH1!"]:
                result = validator.validate(pwd)
                assert 0 <= result["score"] <= 5, (
                    f"Score {result['score']} for '{pwd}' is outside range [0, 5]"
                )
        finally:
            sys.path.pop(0)

    # === Functional Checks ===

    def test_fully_valid_password(self):
        """Verify a password meeting all rules returns valid=True, score=5, no errors"""
        sys.path.insert(0, self.REPO_DIR)
        try:
            from src.python_starter.password_validator import PasswordValidator
            validator = PasswordValidator()
            result = validator.validate("Str0ng!Pass")
            assert result["valid"] is True, f"Expected valid=True for 'Str0ng!Pass', got {result}"
            assert result["score"] == 5, f"Expected score=5, got {result['score']}"
            assert result["errors"] == [], f"Expected no errors, got {result['errors']}"
        finally:
            sys.path.pop(0)

    def test_empty_string_all_rules_fail(self):
        """Verify empty string returns valid=False, score=0, all five error messages"""
        sys.path.insert(0, self.REPO_DIR)
        try:
            from src.python_starter.password_validator import PasswordValidator
            validator = PasswordValidator()
            result = validator.validate("")
            assert result["valid"] is False, "Empty string should be invalid"
            assert result["score"] == 0, f"Expected score=0 for empty string, got {result['score']}"
            assert len(result["errors"]) == 5, (
                f"Expected 5 error messages for empty string, got {len(result['errors'])}: {result['errors']}"
            )
        finally:
            sys.path.pop(0)

    def test_missing_uppercase_only(self):
        """Verify password missing only uppercase letter fails with correct error"""
        sys.path.insert(0, self.REPO_DIR)
        try:
            from src.python_starter.password_validator import PasswordValidator
            validator = PasswordValidator()
            # Has length>=8, lowercase, digit, special — missing uppercase
            result = validator.validate("abcdefg1!")
            assert result["valid"] is False, "Should be invalid without uppercase"
            assert result["score"] == 4, f"Expected score=4, got {result['score']}"
            error_texts = " ".join(result["errors"]).lower()
            assert "uppercase" in error_texts, (
                f"Expected uppercase error, got: {result['errors']}"
            )
        finally:
            sys.path.pop(0)

    def test_missing_lowercase_only(self):
        """Verify password missing only lowercase letter fails with correct error"""
        sys.path.insert(0, self.REPO_DIR)
        try:
            from src.python_starter.password_validator import PasswordValidator
            validator = PasswordValidator()
            result = validator.validate("ALLUPPERCASE1!")
            assert result["valid"] is False, "Should be invalid without lowercase"
            assert result["score"] == 4, f"Expected score=4, got {result['score']}"
            error_texts = " ".join(result["errors"]).lower()
            assert "lowercase" in error_texts, (
                f"Expected lowercase error, got: {result['errors']}"
            )
        finally:
            sys.path.pop(0)

    def test_missing_digit_only(self):
        """Verify password missing only a digit fails with correct error"""
        sys.path.insert(0, self.REPO_DIR)
        try:
            from src.python_starter.password_validator import PasswordValidator
            validator = PasswordValidator()
            result = validator.validate("Abcdefgh!")
            assert result["valid"] is False, "Should be invalid without digit"
            assert result["score"] == 4, f"Expected score=4, got {result['score']}"
            error_texts = " ".join(result["errors"]).lower()
            assert "digit" in error_texts, (
                f"Expected digit error, got: {result['errors']}"
            )
        finally:
            sys.path.pop(0)

    def test_missing_special_char_only(self):
        """Verify password missing only special character fails with correct error"""
        sys.path.insert(0, self.REPO_DIR)
        try:
            from src.python_starter.password_validator import PasswordValidator
            validator = PasswordValidator()
            result = validator.validate("Abcdefg1x")
            assert result["valid"] is False, "Should be invalid without special character"
            assert result["score"] == 4, f"Expected score=4, got {result['score']}"
            error_texts = " ".join(result["errors"]).lower()
            assert "special" in error_texts, (
                f"Expected special character error, got: {result['errors']}"
            )
        finally:
            sys.path.pop(0)

    def test_short_password(self):
        """Verify password shorter than 8 chars fails with length error"""
        sys.path.insert(0, self.REPO_DIR)
        try:
            from src.python_starter.password_validator import PasswordValidator
            validator = PasswordValidator()
            result = validator.validate("Aa1!")
            assert result["valid"] is False, "Short password should be invalid"
            error_texts = " ".join(result["errors"]).lower()
            assert "8 characters" in error_texts or "length" in error_texts, (
                f"Expected length error, got: {result['errors']}"
            )
        finally:
            sys.path.pop(0)

    def test_none_input_raises_type_error(self):
        """Verify that validate(None) raises TypeError"""
        sys.path.insert(0, self.REPO_DIR)
        try:
            from src.python_starter.password_validator import PasswordValidator
            validator = PasswordValidator()
            with pytest.raises(TypeError):
                validator.validate(None)
        finally:
            sys.path.pop(0)

    def test_integer_input_raises_type_error(self):
        """Verify that validate(12345) raises TypeError"""
        sys.path.insert(0, self.REPO_DIR)
        try:
            from src.python_starter.password_validator import PasswordValidator
            validator = PasswordValidator()
            with pytest.raises(TypeError):
                validator.validate(12345)
        finally:
            sys.path.pop(0)

    def test_whitespace_only_string(self):
        """Verify whitespace-only string of length>=8 counts for length but not other rules"""
        sys.path.insert(0, self.REPO_DIR)
        try:
            from src.python_starter.password_validator import PasswordValidator
            validator = PasswordValidator()
            result = validator.validate("        ")  # 8 spaces
            assert result["valid"] is False, "Whitespace-only should be invalid"
            # Length rule passes (8 chars), but uppercase/lowercase/digit/special fail
            assert result["score"] == 1, (
                f"Expected score=1 for 8-space string (only length passes), got {result['score']}"
            )
            assert len(result["errors"]) == 4, (
                f"Expected 4 errors, got {len(result['errors'])}: {result['errors']}"
            )
        finally:
            sys.path.pop(0)

    def test_exact_error_message_strings(self):
        """Verify the exact error message strings match specification"""
        sys.path.insert(0, self.REPO_DIR)
        try:
            from src.python_starter.password_validator import PasswordValidator
            validator = PasswordValidator()
            result = validator.validate("")
            expected_messages = {
                "Password must be at least 8 characters",
                "Password must contain at least one uppercase letter",
                "Password must contain at least one lowercase letter",
                "Password must contain at least one digit",
                "Password must contain at least one special character",
            }
            actual_messages = set(result["errors"])
            assert actual_messages == expected_messages, (
                f"Error messages mismatch.\nExpected: {expected_messages}\nActual: {actual_messages}"
            )
        finally:
            sys.path.pop(0)

    def test_pytest_runs_agent_tests_successfully(self):
        """Verify the agent's own test suite passes"""
        result = subprocess.run(
            ["python", "-m", "pytest", "tests/test_password_validator.py", "-v", "--tb=short"],
            cwd=self.REPO_DIR,
            capture_output=True,
            text=True,
            timeout=120,
        )
        assert result.returncode == 0, (
            f"Agent test suite failed (exit {result.returncode}).\n"
            f"stdout: {result.stdout[-1000:]}\nstderr: {result.stderr[-500:]}"
        )

    def test_coverage_meets_threshold(self):
        """Verify line coverage of password_validator.py is >= 80%"""
        try:
            subprocess.run(
                ["pip", "install", "pytest-cov"],
                cwd=self.REPO_DIR,
                capture_output=True,
                timeout=60,
            )
        except Exception:
            pytest.skip("Could not install pytest-cov")

        result = subprocess.run(
            [
                "python", "-m", "pytest",
                "--cov=src/python_starter/password_validator",
                "--cov-report=term-missing",
                "tests/test_password_validator.py",
            ],
            cwd=self.REPO_DIR,
            capture_output=True,
            text=True,
            timeout=120,
        )
        # Parse coverage percentage from output
        import re
        match = re.search(r'password_validator\s+\d+\s+\d+\s+(\d+)%', result.stdout)
        if match:
            coverage = int(match.group(1))
            assert coverage >= 80, (
                f"Coverage is {coverage}%, expected >= 80%. Output:\n{result.stdout[-500:]}"
            )
        else:
            # If we can't parse, at least ensure tests passed
            assert result.returncode == 0, (
                f"Coverage run failed: {result.stdout[-500:]}\n{result.stderr[-500:]}"
            )
