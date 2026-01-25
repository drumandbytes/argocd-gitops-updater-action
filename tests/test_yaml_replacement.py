"""Tests for YAML replacement functions."""

import pytest
from importlib.machinery import SourceFileLoader
from importlib.util import spec_from_loader, module_from_spec
from pathlib import Path


# Load update-versions.py as a module
def load_update_versions():
    script_path = Path(__file__).parent.parent / ".github" / "scripts" / "update-versions.py"
    loader = SourceFileLoader("update_versions", str(script_path))
    spec = spec_from_loader("update_versions", loader)
    module = module_from_spec(spec)
    loader.exec_module(module)
    return module


update_versions = load_update_versions()


class TestReplaceYamlScalar:
    """Tests for replace_yaml_scalar function."""

    def test_unquoted_value(self):
        """Test replacing unquoted YAML value."""
        text = "targetRevision: 1.0.0\n"
        new_text, count = update_versions.replace_yaml_scalar(text, "targetRevision", "1.0.0", "2.0.0")
        assert count == 1
        assert "targetRevision: 2.0.0" in new_text

    def test_double_quoted_value(self):
        """Test replacing double-quoted YAML value."""
        text = 'version: "1.0.0"\n'
        new_text, count = update_versions.replace_yaml_scalar(text, "version", "1.0.0", "2.0.0")
        assert count == 1
        assert 'version: "2.0.0"' in new_text

    def test_single_quoted_value(self):
        """Test replacing single-quoted YAML value."""
        text = "version: '1.0.0'\n"
        new_text, count = update_versions.replace_yaml_scalar(text, "version", "1.0.0", "2.0.0")
        assert count == 1
        assert "version: '2.0.0'" in new_text

    def test_preserves_indentation(self):
        """Test that indentation is preserved."""
        text = "spec:\n  source:\n    targetRevision: 1.0.0\n"
        new_text, count = update_versions.replace_yaml_scalar(text, "targetRevision", "1.0.0", "2.0.0")
        assert count == 1
        assert "    targetRevision: 2.0.0" in new_text

    def test_no_match(self):
        """Test when there's no match."""
        text = "version: 3.0.0\n"
        new_text, count = update_versions.replace_yaml_scalar(text, "version", "1.0.0", "2.0.0")
        assert count == 0
        assert new_text == text

    def test_only_replaces_first(self):
        """Test that only the first occurrence is replaced."""
        text = "version: 1.0.0\nversion: 1.0.0\n"
        new_text, count = update_versions.replace_yaml_scalar(text, "version", "1.0.0", "2.0.0")
        assert count == 1
        # Should have one 2.0.0 and one 1.0.0
        assert "version: 2.0.0" in new_text
        assert new_text.count("2.0.0") == 1

    def test_with_comment(self):
        """Test value with trailing comment."""
        text = "version: 1.0.0  # current version\n"
        new_text, count = update_versions.replace_yaml_scalar(text, "version", "1.0.0", "2.0.0")
        assert count == 1
        assert "version: 2.0.0  # current version" in new_text

    def test_image_replacement(self):
        """Test replacing Docker image values."""
        text = "image: postgres:16.1\n"
        new_text, count = update_versions.replace_yaml_scalar(text, "image", "postgres:16.1", "postgres:16.2")
        assert count == 1
        assert "image: postgres:16.2" in new_text

    def test_complex_image(self):
        """Test replacing complex image with registry."""
        text = "image: ghcr.io/owner/repo:v1.0.0\n"
        new_text, count = update_versions.replace_yaml_scalar(
            text, "image", "ghcr.io/owner/repo:v1.0.0", "ghcr.io/owner/repo:v2.0.0"
        )
        assert count == 1
        assert "image: ghcr.io/owner/repo:v2.0.0" in new_text
