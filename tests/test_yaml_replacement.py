"""Tests for YAML replacement functions."""

from importlib.machinery import SourceFileLoader
from importlib.util import module_from_spec, spec_from_loader
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

    def test_new_tag_unquoted(self):
        """Test replacing unquoted newTag value in kustomization.yaml."""
        text = "images:\n  - name: ghost\n    newTag: 6.14.0-alpine3.23\n"
        new_text, count = update_versions.replace_yaml_scalar(text, "newTag", "6.14.0-alpine3.23", "6.15.0-alpine3.23")
        assert count == 1
        assert "newTag: 6.15.0-alpine3.23" in new_text

    def test_new_tag_quoted(self):
        """Test replacing quoted newTag value in kustomization.yaml."""
        text = 'images:\n  - name: curlimages/curl\n    newTag: "8.12.1"\n'
        new_text, count = update_versions.replace_yaml_scalar(text, "newTag", "8.12.1", "8.13.0")
        assert count == 1
        assert 'newTag: "8.13.0"' in new_text

    def test_new_tag_only_replaces_first(self):
        """Test that only the first newTag occurrence is replaced when values differ."""
        text = "images:\n  - name: app\n    newTag: 1.0.0\n  - name: other\n    newTag: 2.0.0\n"
        new_text, count = update_versions.replace_yaml_scalar(text, "newTag", "1.0.0", "1.1.0")
        assert count == 1
        assert "newTag: 1.1.0" in new_text
        assert "newTag: 2.0.0" in new_text


class TestReplaceYamlNewTag:
    """Tests for replace_yaml_new_tag (context-aware newTag replacement)."""

    def test_targets_correct_image_by_name(self):
        """Test that replacement targets the correct image when multiple share the same tag."""
        text = (
            "images:\n"
            "  - name: ghcr.io/owner/app\n"
            "    newTag: latest\n"
            "  - name: ghcr.io/owner/init\n"
            "    newTag: latest\n"
            "  - name: curlimages/curl\n"
            '    newTag: "8.12.1"\n'
        )
        # Update only the second image (init)
        new_text, count = update_versions.replace_yaml_new_tag(text, "ghcr.io/owner/init", "latest", "1.2.0")
        assert count == 1
        # First image should still be "latest"
        assert "  - name: ghcr.io/owner/app\n    newTag: latest\n" in new_text
        # Second image should be updated
        assert "  - name: ghcr.io/owner/init\n    newTag: 1.2.0\n" in new_text

    def test_preserves_quotes(self):
        """Test that quotes around newTag value are preserved."""
        text = 'images:\n  - name: curlimages/curl\n    newTag: "8.12.1"\n'
        new_text, count = update_versions.replace_yaml_new_tag(text, "curlimages/curl", "8.12.1", "8.13.0")
        assert count == 1
        assert 'newTag: "8.13.0"' in new_text

    def test_handles_intermediate_fields(self):
        """Test that intermediate fields between name and newTag are handled."""
        text = "images:\n  - name: ghost\n    newName: ghcr.io/ghost/ghost\n    newTag: 6.14.0\n"
        new_text, count = update_versions.replace_yaml_new_tag(text, "ghost", "6.14.0", "6.15.0")
        assert count == 1
        assert "newTag: 6.15.0" in new_text
        assert "newName: ghcr.io/ghost/ghost" in new_text

    def test_falls_back_to_generic_on_no_match(self):
        """Test fallback to replace_yaml_scalar when name doesn't match."""
        text = "images:\n  - name: other\n    newTag: 1.0.0\n"
        # Using a non-matching name should fall back
        new_text, count = update_versions.replace_yaml_new_tag(text, "nonexistent", "1.0.0", "2.0.0")
        # Fallback should still find and replace the value
        assert count == 1
        assert "newTag: 2.0.0" in new_text


class TestFindMatchingHelmSource:
    """Tests for _find_matching_helm_source - covers both Argo CD
    Application source shapes. Mirrors discover-resources.py's
    _find_helm_source tests, but this one matches by chart name since a
    multi-source app pairs a Helm chart source with a companion git source."""

    def test_legacy_single_source(self):
        spec = {"source": {"chart": "grafana", "repoURL": "https://example.com/charts", "targetRevision": "1.0.0"}}
        source = update_versions._find_matching_helm_source(spec, "grafana")
        assert source is not None
        assert source["targetRevision"] == "1.0.0"

    def test_multi_source_matches_by_chart_name(self):
        """This is the exact shape that was silently unsupported before -
        every multi-source Application in a real consuming repo (Helm chart
        source paired with a companion git/directory source) meant
        update_argo_app_chart always fell through to 'no spec.source,
        skipping' and never updated anything."""
        spec = {
            "sources": [
                {
                    "chart": "sealed-secrets",
                    "repoURL": "https://bitnami-labs.github.io/sealed-secrets",
                    "targetRevision": "2.19.3",
                },
                {"repoURL": "https://github.com/example/repo", "path": "apps/sealed-secrets"},
            ]
        }
        source = update_versions._find_matching_helm_source(spec, "sealed-secrets")
        assert source is not None
        assert source["targetRevision"] == "2.19.3"

    def test_multi_source_wrong_chart_name_no_match(self):
        """Must match by chart name, not just 'the first source with a
        chart key' - otherwise a repo tracking multiple different charts
        across different Applications could patch the wrong one."""
        spec = {
            "sources": [
                {"chart": "grafana", "repoURL": "https://example.com/charts", "targetRevision": "1.0.0"},
            ]
        }
        assert update_versions._find_matching_helm_source(spec, "sealed-secrets") is None

    def test_no_source_or_sources(self):
        assert update_versions._find_matching_helm_source({}, "grafana") is None
