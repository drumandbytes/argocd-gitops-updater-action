"""Tests for ignore rule functions."""

import pytest
import re
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


class TestBuildIgnoreLookups:
    """Tests for build_ignore_lookups function."""

    def test_empty_config(self):
        """Test with empty/None config."""
        docker_ignore, helm_ignore = update_versions.build_ignore_lookups(None)
        assert docker_ignore == {}
        assert helm_ignore == {}

    def test_docker_ignore_by_id(self):
        """Test Docker image ignore by ID."""
        config = {
            "dockerImages": [
                {"id": "postgres"},
                {"id": "redis", "versionPattern": r"^7\."},
            ]
        }
        docker_ignore, helm_ignore = update_versions.build_ignore_lookups(config)

        assert "postgres" in docker_ignore
        assert "redis" in docker_ignore
        assert "_compiled_version_pattern" in docker_ignore["redis"]
        assert helm_ignore == {}

    def test_helm_ignore_by_name(self):
        """Test Helm chart ignore by name."""
        config = {
            "helmCharts": [
                {"name": "prometheus"},
                {"name": "grafana", "versionPattern": r"^6\."},
            ]
        }
        docker_ignore, helm_ignore = update_versions.build_ignore_lookups(config)

        assert docker_ignore == {}
        assert "prometheus" in helm_ignore
        assert "grafana" in helm_ignore
        assert "_compiled_version_pattern" in helm_ignore["grafana"]

    def test_compiled_patterns(self):
        """Test that regex patterns are pre-compiled."""
        config = {
            "dockerImages": [
                {"id": "test", "versionPattern": r"^\d+\.\d+$", "tagPattern": r".*-alpine"}
            ]
        }
        docker_ignore, _ = update_versions.build_ignore_lookups(config)

        rule = docker_ignore["test"]
        assert "_compiled_version_pattern" in rule
        assert "_compiled_tag_pattern" in rule
        assert isinstance(rule["_compiled_version_pattern"], re.Pattern)
        assert isinstance(rule["_compiled_tag_pattern"], re.Pattern)


class TestShouldIgnoreDockerImage:
    """Tests for should_ignore_docker_image function."""

    def test_no_ignore_rules(self):
        """Test with no ignore rules."""
        entry = {"id": "postgres"}
        ignored, reason = update_versions.should_ignore_docker_image(entry, "16.1", {})
        assert ignored is False
        assert reason is None

    def test_ignore_by_id(self):
        """Test ignoring by ID without version pattern."""
        docker_ignore = {"postgres": {"id": "postgres"}}
        entry = {"id": "postgres"}
        ignored, reason = update_versions.should_ignore_docker_image(entry, "16.1", docker_ignore)
        assert ignored is True
        assert "ignored by ID" in reason

    def test_ignore_with_version_pattern(self):
        """Test that version pattern allows image but filters versions."""
        docker_ignore = {
            "postgres": {
                "id": "postgres",
                "versionPattern": r"^17\.",
                "_compiled_version_pattern": re.compile(r"^17\."),
            }
        }
        entry = {"id": "postgres"}
        # Should NOT be ignored entirely when there's a version pattern
        ignored, reason = update_versions.should_ignore_docker_image(entry, "16.1", docker_ignore)
        assert ignored is False

    def test_ignore_with_tag_pattern(self):
        """Test ignoring by tag pattern.

        Note: tagPattern is only checked when versionPattern is also present.
        Without versionPattern, the image is ignored entirely by ID.
        """
        docker_ignore = {
            "postgres": {
                "id": "postgres",
                "versionPattern": r"^17\.",  # Need this to enable tag pattern check
                "_compiled_version_pattern": re.compile(r"^17\."),
                "tagPattern": r".*-alpine",
                "_compiled_tag_pattern": re.compile(r".*-alpine"),
            }
        }
        entry = {"id": "postgres"}
        # Tag matches pattern, so should be ignored
        ignored, reason = update_versions.should_ignore_docker_image(entry, "16.1-alpine", docker_ignore)
        assert ignored is True
        assert "tag pattern" in reason

        # Tag doesn't match pattern, so should not be ignored
        ignored, reason = update_versions.should_ignore_docker_image(entry, "16.1", docker_ignore)
        assert ignored is False


class TestShouldIgnoreHelmChart:
    """Tests for should_ignore_helm_chart function."""

    def test_no_ignore_rules(self):
        """Test with no ignore rules."""
        ignored, reason = update_versions.should_ignore_helm_chart("prometheus", "25.0.0", {})
        assert ignored is False
        assert reason is None

    def test_ignore_by_name(self):
        """Test ignoring by name."""
        helm_ignore = {"prometheus": {"name": "prometheus"}}
        ignored, reason = update_versions.should_ignore_helm_chart("prometheus", "25.0.0", helm_ignore)
        assert ignored is True
        assert "ignored by name" in reason

    def test_ignore_with_version_pattern(self):
        """Test ignoring by name and version pattern."""
        helm_ignore = {
            "prometheus": {
                "name": "prometheus",
                "versionPattern": r"^25\.",
                "_compiled_version_pattern": re.compile(r"^25\."),
            }
        }
        # Version matches pattern - should be ignored
        ignored, reason = update_versions.should_ignore_helm_chart("prometheus", "25.0.0", helm_ignore)
        assert ignored is True

        # Version doesn't match pattern - should not be ignored
        ignored, reason = update_versions.should_ignore_helm_chart("prometheus", "24.0.0", helm_ignore)
        assert ignored is False

    def test_non_matching_chart(self):
        """Test chart not in ignore list."""
        helm_ignore = {"prometheus": {"name": "prometheus"}}
        ignored, reason = update_versions.should_ignore_helm_chart("grafana", "10.0.0", helm_ignore)
        assert ignored is False
