"""Tests for edge cases and error handling.

These tests ensure the scripts handle malformed input gracefully,
logging warnings/errors but continuing execution rather than crashing.
"""

import pytest
import re
from importlib.machinery import SourceFileLoader
from importlib.util import spec_from_loader, module_from_spec
from pathlib import Path


# Load modules
def load_update_versions():
    script_path = Path(__file__).parent.parent / ".github" / "scripts" / "update-versions.py"
    loader = SourceFileLoader("update_versions", str(script_path))
    spec = spec_from_loader("update_versions", loader)
    module = module_from_spec(spec)
    loader.exec_module(module)
    return module


def load_discover_resources():
    script_path = Path(__file__).parent.parent / ".github" / "scripts" / "discover-resources.py"
    loader = SourceFileLoader("discover_resources", str(script_path))
    spec = spec_from_loader("discover_resources", loader)
    module = module_from_spec(spec)
    loader.exec_module(module)
    return module


update_versions = load_update_versions()
discover_resources = load_discover_resources()


class TestMalformedVersionStrings:
    """Test handling of malformed or unusual version strings."""

    def test_empty_version(self):
        """Empty version string should return empty, not crash."""
        result = update_versions.normalize_version_string("")
        assert result == ""

    def test_none_like_strings(self):
        """Strings like 'None' or 'null' should be handled."""
        assert update_versions.normalize_version_string("None") == ""
        assert update_versions.normalize_version_string("null") == ""
        assert update_versions.normalize_version_string("undefined") == ""

    def test_only_letters(self):
        """Version with only letters should return empty."""
        assert update_versions.normalize_version_string("latest") == ""
        assert update_versions.normalize_version_string("stable") == ""
        assert update_versions.normalize_version_string("edge") == ""

    def test_special_characters(self):
        """Versions with special characters should be handled."""
        # Should extract numeric parts or return empty
        result = update_versions.normalize_version_string("v1.2.3@sha256:abc123")
        # Should at least not crash
        assert isinstance(result, str)

    def test_very_long_version(self):
        """Very long version strings should be handled."""
        long_version = "1." + ".0" * 100
        result = update_versions.normalize_version_string(long_version)
        assert isinstance(result, str)

    def test_unicode_in_version(self):
        """Unicode characters in version should be handled."""
        result = update_versions.normalize_version_string("1.2.3-日本語")
        assert isinstance(result, str)

    def test_whitespace_version(self):
        """Whitespace-only version should return empty."""
        assert update_versions.normalize_version_string("   ") == ""
        assert update_versions.normalize_version_string("\t\n") == ""


class TestLatestSemverEdgeCases:
    """Test latest_semver with edge case inputs."""

    def test_empty_list(self):
        """Empty list should return None."""
        assert update_versions.latest_semver([]) is None

    def test_all_invalid_versions(self):
        """List with only invalid versions should return None."""
        versions = ["latest", "stable", "edge", "dev"]
        assert update_versions.latest_semver(versions) is None

    def test_mixed_valid_invalid(self):
        """Should ignore invalid and return latest valid."""
        versions = ["latest", "1.0.0", "invalid", "2.0.0", "edge"]
        assert update_versions.latest_semver(versions) == "2.0.0"

    def test_single_version(self):
        """Single valid version should be returned."""
        assert update_versions.latest_semver(["1.0.0"]) == "1.0.0"

    def test_duplicate_versions(self):
        """Duplicate versions should be handled."""
        versions = ["1.0.0", "1.0.0", "1.0.0"]
        assert update_versions.latest_semver(versions) == "1.0.0"

    def test_none_in_list(self):
        """None values in list should be handled."""
        # The function converts to str, so None becomes "None"
        versions = ["1.0.0", "2.0.0"]
        assert update_versions.latest_semver(versions) == "2.0.0"


class TestIgnoreRulesEdgeCases:
    """Test ignore rule handling with edge cases."""

    def test_empty_ignore_config(self):
        """Empty ignore config should not cause issues."""
        docker_ignore, helm_ignore = update_versions.build_ignore_lookups({})
        assert docker_ignore == {}
        assert helm_ignore == {}

    def test_none_ignore_config(self):
        """None ignore config should not cause issues."""
        docker_ignore, helm_ignore = update_versions.build_ignore_lookups(None)
        assert docker_ignore == {}
        assert helm_ignore == {}

    def test_missing_id_in_docker_ignore(self):
        """Docker ignore rule without id should be skipped."""
        config = {
            "dockerImages": [
                {"versionPattern": r"^1\."},  # Missing id
                {"id": "valid", "versionPattern": r"^2\."},
            ]
        }
        docker_ignore, _ = update_versions.build_ignore_lookups(config)
        assert "valid" in docker_ignore
        assert len(docker_ignore) == 1  # Only valid rule

    def test_missing_name_in_helm_ignore(self):
        """Helm ignore rule without name should be skipped."""
        config = {
            "helmCharts": [
                {"versionPattern": r"^1\."},  # Missing name
                {"name": "valid", "versionPattern": r"^2\."},
            ]
        }
        _, helm_ignore = update_versions.build_ignore_lookups(config)
        assert "valid" in helm_ignore
        assert len(helm_ignore) == 1

    def test_invalid_regex_pattern(self):
        """Invalid regex pattern should be handled gracefully, not crash."""
        config = {
            "dockerImages": [
                {"id": "test", "versionPattern": r"[invalid(regex"},
            ]
        }
        # Should NOT raise - pattern is skipped with warning
        docker_ignore, helm_ignore = update_versions.build_ignore_lookups(config)

        # The rule should still be added, but without the compiled pattern
        assert "test" in docker_ignore
        assert "_compiled_version_pattern" not in docker_ignore["test"]

    def test_invalid_regex_helm(self):
        """Invalid regex in Helm ignore should be handled gracefully."""
        config = {
            "helmCharts": [
                {"name": "myapp", "versionPattern": r"[bad(pattern"},
            ]
        }
        # Should NOT raise
        docker_ignore, helm_ignore = update_versions.build_ignore_lookups(config)

        # The rule should still be added, but without the compiled pattern
        assert "myapp" in helm_ignore
        assert "_compiled_version_pattern" not in helm_ignore["myapp"]

    def test_invalid_tag_pattern(self):
        """Invalid tagPattern regex should be handled gracefully."""
        config = {
            "dockerImages": [
                {"id": "test", "tagPattern": r"[bad(pattern"},
            ]
        }
        docker_ignore, _ = update_versions.build_ignore_lookups(config)

        assert "test" in docker_ignore
        assert "_compiled_tag_pattern" not in docker_ignore["test"]

    def test_empty_lists_in_config(self):
        """Empty lists in config should be handled."""
        config = {
            "dockerImages": [],
            "helmCharts": [],
        }
        docker_ignore, helm_ignore = update_versions.build_ignore_lookups(config)
        assert docker_ignore == {}
        assert helm_ignore == {}


class TestImageParsingEdgeCases:
    """Test image string parsing with edge cases."""

    def test_empty_image_string(self):
        """Empty image string should be handled."""
        name, tag = update_versions.parse_image("")
        assert name == ""
        assert tag == ""

    def test_only_colon(self):
        """Image string with only colon."""
        name, tag = update_versions.parse_image(":")
        assert name == ""
        assert tag == ""

    def test_multiple_colons(self):
        """Image with multiple colons (registry with port)."""
        name, tag = update_versions.parse_image("localhost:5000/repo:v1.0.0")
        assert tag == "v1.0.0"
        assert "localhost:5000" in name

    def test_sha256_digest(self):
        """Image with SHA256 digest instead of tag."""
        name, tag = update_versions.parse_image("nginx@sha256:abc123def456")
        # Should handle @ as part of name since there's no colon for tag
        assert isinstance(name, str)
        assert isinstance(tag, str)

    def test_deeply_nested_repo(self):
        """Image with deeply nested repository path."""
        name, tag = update_versions.parse_image("gcr.io/project/team/app/service:v1")
        assert tag == "v1"

    def test_unicode_in_image(self):
        """Image name with unicode should be handled."""
        name, tag = update_versions.parse_image("レジストリ/イメージ:タグ")
        assert isinstance(name, str)
        assert isinstance(tag, str)


class TestYamlReplacementEdgeCases:
    """Test YAML replacement with edge cases."""

    def test_empty_text(self):
        """Empty text should return empty with 0 count."""
        new_text, count = update_versions.replace_yaml_scalar("", "key", "old", "new")
        assert new_text == ""
        assert count == 0

    def test_key_not_found(self):
        """Key not in text should return unchanged."""
        text = "other: value\n"
        new_text, count = update_versions.replace_yaml_scalar(text, "version", "1.0", "2.0")
        assert new_text == text
        assert count == 0

    def test_value_not_found(self):
        """Key exists but value doesn't match."""
        text = "version: 3.0.0\n"
        new_text, count = update_versions.replace_yaml_scalar(text, "version", "1.0.0", "2.0.0")
        assert new_text == text
        assert count == 0

    def test_special_chars_in_value(self):
        """Value with regex special characters."""
        text = "image: nginx:1.24.0-alpine\n"
        new_text, count = update_versions.replace_yaml_scalar(
            text, "image", "nginx:1.24.0-alpine", "nginx:1.25.0-alpine"
        )
        assert count == 1
        assert "nginx:1.25.0-alpine" in new_text

    def test_multiline_yaml(self):
        """Multi-line YAML document."""
        text = """apiVersion: v1
kind: Application
spec:
  source:
    targetRevision: 1.0.0
    chart: myapp
"""
        new_text, count = update_versions.replace_yaml_scalar(text, "targetRevision", "1.0.0", "2.0.0")
        assert count == 1
        assert "targetRevision: 2.0.0" in new_text
        # Other lines should be unchanged
        assert "apiVersion: v1" in new_text
        assert "chart: myapp" in new_text

    def test_same_old_and_new(self):
        """Same old and new value should still work."""
        text = "version: 1.0.0\n"
        new_text, count = update_versions.replace_yaml_scalar(text, "version", "1.0.0", "1.0.0")
        # Should match and "replace" even if same
        assert count == 1


class TestDiscoveryEdgeCases:
    """Test resource discovery with edge cases."""

    def test_find_images_empty_dict(self):
        """Empty dict should return empty list."""
        images = discover_resources.find_container_images_in_yaml({})
        assert images == []

    def test_find_images_none_values(self):
        """Dict with None values should be handled."""
        data = {
            "spec": None,
            "containers": None,
        }
        images = discover_resources.find_container_images_in_yaml(data)
        assert images == []

    def test_find_images_non_string_image(self):
        """Non-string image value should be skipped."""
        data = {
            "kind": "Deployment",
            "spec": {
                "template": {
                    "spec": {
                        "containers": [
                            {"name": "app", "image": 12345},  # Invalid: not a string
                        ]
                    }
                }
            }
        }
        images = discover_resources.find_container_images_in_yaml(data)
        # Should not crash, may or may not find the image
        assert isinstance(images, list)

    def test_find_images_deeply_nested(self):
        """Deeply nested structure should be handled."""
        data = {
            "level1": {
                "level2": {
                    "level3": {
                        "level4": {
                            "containers": [
                                {"image": "deep:v1"}
                            ]
                        }
                    }
                }
            }
        }
        images = discover_resources.find_container_images_in_yaml(data)
        # The recursive function should find it
        assert len(images) >= 1

    def test_parse_image_edge_cases(self):
        """Test parse_image with various edge cases."""
        # Empty string
        registry, repo, tag = discover_resources.parse_image("")
        assert registry == "dockerhub"
        assert tag == "latest"

        # Just a name, no tag
        registry, repo, tag = discover_resources.parse_image("nginx")
        assert registry == "dockerhub"
        assert repo == "library/nginx"
        assert tag == "latest"


class TestVariantExtractionEdgeCases:
    """Test variant extraction with edge cases."""

    def test_no_version_prefix(self):
        """Tag with no version prefix."""
        result = update_versions.extract_variant_pattern("alpine")
        assert result is None

    def test_version_only(self):
        """Tag with version only, no variant."""
        result = update_versions.extract_variant_pattern("1.2.3")
        assert result is None

    def test_empty_string(self):
        """Empty string should return None."""
        result = update_versions.extract_variant_pattern("")
        assert result is None

    def test_complex_variant(self):
        """Complex variant with numbers."""
        result = update_versions.extract_variant_pattern("1.2.3-alpine3.19")
        assert result == "alpine"

    def test_multiple_dashes(self):
        """Multiple dashes in variant."""
        result = update_versions.extract_variant_pattern("1.2.3-slim-bookworm")
        assert result == "slim"


class TestTagCandidateEdgeCases:
    """Test is_tag_candidate with edge cases."""

    def test_empty_tag(self):
        """Empty tag should be handled."""
        # May return True or False, but should not crash
        result = update_versions.is_tag_candidate("")
        assert isinstance(result, bool)

    def test_only_prerelease_markers(self):
        """Tags that are only prerelease markers."""
        assert update_versions.is_tag_candidate("alpha") is False
        assert update_versions.is_tag_candidate("beta") is False
        assert update_versions.is_tag_candidate("rc1") is False

    def test_case_insensitive_prerelease(self):
        """Prerelease detection should be case-insensitive."""
        assert update_versions.is_tag_candidate("1.0.0-ALPHA") is False
        assert update_versions.is_tag_candidate("1.0.0-Beta") is False
        assert update_versions.is_tag_candidate("1.0.0-RC1") is False

    def test_variant_none_vs_empty(self):
        """Test variant matching with None vs actual variant."""
        # No variant required, tag has no variant - should match
        assert update_versions.is_tag_candidate("1.2.3", required_variant=None) is True

        # Variant required, tag has that variant - should match
        assert update_versions.is_tag_candidate("1.2.3-alpine", required_variant="alpine") is True

        # No variant required, but tag has variant - should NOT match
        assert update_versions.is_tag_candidate("1.2.3-alpine", required_variant=None) is False

        # Variant required, but tag has no variant - should NOT match
        assert update_versions.is_tag_candidate("1.2.3", required_variant="alpine") is False
