"""Tests for resource discovery functions."""

from importlib.machinery import SourceFileLoader
from importlib.util import module_from_spec, spec_from_loader
from pathlib import Path


# Load discover-resources.py as a module
def load_discover_resources():
    script_path = Path(__file__).parent.parent / ".github" / "scripts" / "discover-resources.py"
    loader = SourceFileLoader("discover_resources", str(script_path))
    spec = spec_from_loader("discover_resources", loader)
    module = module_from_spec(spec)
    loader.exec_module(module)
    return module


discover_resources = load_discover_resources()


class TestParseImage:
    """Tests for parse_image function in discover-resources."""

    def test_dockerhub_official(self):
        """Test Docker Hub official image."""
        registry, repo, tag = discover_resources.parse_image("postgres:16.1")
        assert registry == "dockerhub"
        assert repo == "library/postgres"
        assert tag == "16.1"

    def test_dockerhub_user(self):
        """Test Docker Hub user image."""
        registry, repo, tag = discover_resources.parse_image("cloudflare/cloudflared:2025.11.1")
        assert registry == "dockerhub"
        assert repo == "cloudflare/cloudflared"
        assert tag == "2025.11.1"

    def test_ghcr(self):
        """Test GitHub Container Registry."""
        registry, repo, tag = discover_resources.parse_image("ghcr.io/owner/repo:v1.0.0")
        assert registry == "ghcr.io"
        assert repo == "owner/repo"
        assert tag == "v1.0.0"

    def test_gcr(self):
        """Test Google Container Registry."""
        registry, repo, tag = discover_resources.parse_image("gcr.io/project/image:latest")
        assert registry == "gcr.io"
        assert repo == "project/image"
        assert tag == "latest"

    def test_quay(self):
        """Test Quay.io."""
        registry, repo, tag = discover_resources.parse_image("quay.io/prometheus/prometheus:v2.48.0")
        assert registry == "quay.io"
        assert repo == "prometheus/prometheus"
        assert tag == "v2.48.0"

    def test_no_tag(self):
        """Test image without tag."""
        registry, repo, tag = discover_resources.parse_image("nginx")
        assert registry == "dockerhub"
        assert repo == "library/nginx"
        assert tag == "latest"

    def test_custom_registry(self):
        """Test custom registry with port."""
        registry, repo, tag = discover_resources.parse_image("my.registry.io:5000/app:v1")
        assert registry == "my.registry.io:5000"
        assert repo == "app"
        assert tag == "v1"


class TestFindContainerImages:
    """Tests for find_container_images_in_yaml function."""

    def test_simple_deployment(self):
        """Test finding image in simple deployment."""
        data = {
            "kind": "Deployment",
            "spec": {"template": {"spec": {"containers": [{"name": "app", "image": "nginx:1.24.0"}]}}},
        }
        images = discover_resources.find_container_images_in_yaml(data)
        assert len(images) == 1
        assert images[0][1] == "nginx:1.24.0"

    def test_multiple_containers(self):
        """Test finding images in multiple containers."""
        data = {
            "kind": "Deployment",
            "spec": {
                "template": {
                    "spec": {
                        "containers": [
                            {"name": "app", "image": "nginx:1.24.0"},
                            {"name": "sidecar", "image": "busybox:1.36"},
                        ]
                    }
                }
            },
        }
        images = discover_resources.find_container_images_in_yaml(data)
        assert len(images) == 2

    def test_init_containers(self):
        """Test finding images in init containers."""
        data = {
            "kind": "Deployment",
            "spec": {
                "template": {
                    "spec": {
                        "initContainers": [{"name": "init", "image": "busybox:1.36"}],
                        "containers": [{"name": "app", "image": "nginx:1.24.0"}],
                    }
                }
            },
        }
        images = discover_resources.find_container_images_in_yaml(data)
        assert len(images) == 2

    def test_no_images(self):
        """Test data without images."""
        data = {"kind": "ConfigMap", "data": {"key": "value"}}
        images = discover_resources.find_container_images_in_yaml(data)
        assert len(images) == 0


class TestShouldIgnoreDockerImage:
    """Tests for should_ignore_docker_image function in discover-resources."""

    def test_no_ignore_config(self):
        """Test with no ignore config."""
        entry = {"id": "postgres", "repository": "library/postgres"}
        ignored, reason = discover_resources.should_ignore_docker_image(entry, None)
        assert ignored is False

    def test_ignore_by_id(self):
        """Test ignoring by ID."""
        entry = {"id": "postgres", "repository": "library/postgres"}
        ignore_config = {"dockerImages": [{"id": "postgres"}]}
        ignored, reason = discover_resources.should_ignore_docker_image(entry, ignore_config)
        assert ignored is True
        assert "ID" in reason

    def test_ignore_by_repository(self):
        """Test ignoring by repository."""
        entry = {"id": "postgres", "repository": "library/postgres"}
        ignore_config = {"dockerImages": [{"repository": "library/postgres"}]}
        ignored, reason = discover_resources.should_ignore_docker_image(entry, ignore_config)
        assert ignored is True
        assert "repository" in reason


class TestShouldIgnoreHelmChart:
    """Tests for should_ignore_helm_chart function in discover-resources."""

    def test_no_ignore_config(self):
        """Test with no ignore config."""
        ignored, reason = discover_resources.should_ignore_helm_chart("prometheus", None)
        assert ignored is False

    def test_ignore_by_name(self):
        """Test ignoring by name."""
        ignore_config = {"helmCharts": [{"name": "prometheus"}]}
        ignored, reason = discover_resources.should_ignore_helm_chart("prometheus", ignore_config)
        assert ignored is True
        assert "name" in reason

    def test_not_ignored(self):
        """Test chart not in ignore list."""
        ignore_config = {"helmCharts": [{"name": "prometheus"}]}
        ignored, reason = discover_resources.should_ignore_helm_chart("grafana", ignore_config)
        assert ignored is False


class TestFindHelmSource:
    """Tests for _find_helm_source - covers both Argo CD Application source shapes."""

    def test_legacy_single_source(self):
        """The old spec.source shape must still be found."""
        spec = {"source": {"chart": "grafana", "repoURL": "https://example.com/charts"}}
        source = discover_resources._find_helm_source(spec)
        assert source is not None
        assert source["chart"] == "grafana"

    def test_multi_source_helm_chart(self):
        """A multi-source Application (spec.sources[]) must be found too -
        this was completely invisible before, since only spec.source was
        ever checked."""
        spec = {
            "sources": [
                {"chart": "sealed-secrets", "repoURL": "https://bitnami-labs.github.io/sealed-secrets"},
                {"repoURL": "https://github.com/example/repo", "path": "apps/sealed-secrets"},
            ]
        }
        source = discover_resources._find_helm_source(spec)
        assert source is not None
        assert source["chart"] == "sealed-secrets"

    def test_multi_source_chart_not_first(self):
        """The Helm chart source isn't always sources[0] - must not assume order."""
        spec = {
            "sources": [
                {"repoURL": "https://github.com/example/repo", "path": "apps/foo"},
                {"chart": "foo", "repoURL": "https://example.com/charts"},
            ]
        }
        source = discover_resources._find_helm_source(spec)
        assert source is not None
        assert source["chart"] == "foo"

    def test_git_only_multi_source_no_match(self):
        """A multi-source app with no Helm chart source at all (e.g. two git
        sources) should return None, not error."""
        spec = {
            "sources": [
                {"repoURL": "https://github.com/example/repo-a"},
                {"repoURL": "https://github.com/example/repo-b"},
            ]
        }
        assert discover_resources._find_helm_source(spec) is None

    def test_no_source_or_sources(self):
        """A spec with neither key should return None, not raise."""
        assert discover_resources._find_helm_source({}) is None


class TestMergeConfigsPreservesUnknownSections:
    """Tests for merge_configs - covers the top-level section preservation
    fix. Before this, any existing top-level key not in the hardcoded
    {argoApps, kustomizeHelmCharts, chartDependencies, dockerImages, ignore}
    set was silently dropped on every auto-discover run - confirmed against
    a real repo with a manually-maintained 'helmCharts' section (pre-dating
    the argoApps/kustomizeHelmCharts/chartDependencies split) that would
    have been deleted entirely."""

    def test_unknown_section_preserved(self):
        existing = {
            "helmCharts": [{"name": "nfs-subdir-external-provisioner", "repository": "https://example.com"}],
            "dockerImages": [],
        }
        discovered = {"dockerImages": []}
        merged = discover_resources.merge_configs(existing, discovered)
        assert merged["helmCharts"] == existing["helmCharts"]

    def test_known_sections_not_duplicated_as_unknown(self):
        """A known section (dockerImages) must go through its normal merge
        logic, not get double-handled by the preservation fallback."""
        existing = {
            "dockerImages": [
                {
                    "id": "app",
                    "registry": "dockerhub",
                    "repository": "org/app",
                    "currentTag": "1.0.0",
                    "file": "app.yaml",
                    "yamlPath": ["spec", "image"],
                }
            ]
        }
        discovered = {"dockerImages": []}
        merged = discover_resources.merge_configs(existing, discovered)
        assert len(merged["dockerImages"]) == 1
        assert merged["dockerImages"][0]["id"] == "app"

    def test_ignore_section_still_preserved(self):
        """Regression guard: 'ignore' already had its own explicit handling
        before this fix - must keep working unchanged."""
        existing = {"ignore": {"dockerImages": [{"repository": "some/thing"}]}}
        discovered = {}
        merged = discover_resources.merge_configs(existing, discovered)
        assert merged["ignore"] == existing["ignore"]


class TestRoundtripCommentPreservation:
    """Proves the actual end-to-end claim: running a real .update-config.yaml
    through load -> merge_configs -> dump with ruamel.yaml's round-trip mode
    keeps every existing comment intact, while still correctly adding new
    entries discovery finds. A plain yaml.safe_load/yaml.dump round-trip
    (what this script used before) has no concept of comments at all and
    would silently drop every one of these on write."""

    def test_header_and_inline_comments_survive_a_real_merge(self):
        original = """\
# Consumed by update-versions.yml. Re-run discover-versions.yml after
# adding new apps to pick up anything missing here.
argoApps:
  - name: sealed-secrets
    repoUrl: https://bitnami-labs.github.io/sealed-secrets
    file: apps/sealed-secrets/application.yaml
  # newly-added apps go below this line
dockerImages: []
# home-assistant is deliberately NOT tracked - see PR #42 for why.
"""
        existing = discover_resources.load_yaml_roundtrip(original)
        discovered = {
            "argoApps": [
                {
                    "name": "loki",
                    "repoUrl": "https://grafana.github.io/helm-charts",
                    "file": "apps/loki/application.yaml",
                },
            ]
        }

        merged = discover_resources.merge_configs(existing, discovered)
        output = discover_resources.dump_yaml_roundtrip(merged)

        # Every original comment is still there, verbatim.
        assert "# Consumed by update-versions.yml. Re-run discover-versions.yml after" in output
        assert "# newly-added apps go below this line" in output
        assert "# home-assistant is deliberately NOT tracked - see PR #42 for why." in output
        # The existing entry is untouched, and the new one was genuinely added.
        assert "name: sealed-secrets" in output
        assert "name: loki" in output

    def test_existing_empty_section_with_comment_is_not_replaced_wholesale(self):
        """An existing-but-empty section (dockerImages: [] with its own
        trailing comment) must not be discarded just because it's empty -
        confirmed via a real regression this exact scenario would hit if
        merge_configs used truthiness instead of an explicit None check."""
        original = """\
argoApps: []
dockerImages: []  # nothing tracked yet, added on purpose
"""
        existing = discover_resources.load_yaml_roundtrip(original)
        discovered = {"dockerImages": [{"id": "app", "registry": "dockerhub", "repository": "org/app"}]}

        merged = discover_resources.merge_configs(existing, discovered)
        output = discover_resources.dump_yaml_roundtrip(merged)

        assert "# nothing tracked yet, added on purpose" in output
        assert "id: app" in output
