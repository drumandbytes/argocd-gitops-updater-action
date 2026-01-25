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
            "spec": {
                "template": {
                    "spec": {
                        "containers": [
                            {"name": "app", "image": "nginx:1.24.0"}
                        ]
                    }
                }
            }
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
                            {"name": "sidecar", "image": "busybox:1.36"}
                        ]
                    }
                }
            }
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
                        "initContainers": [
                            {"name": "init", "image": "busybox:1.36"}
                        ],
                        "containers": [
                            {"name": "app", "image": "nginx:1.24.0"}
                        ]
                    }
                }
            }
        }
        images = discover_resources.find_container_images_in_yaml(data)
        assert len(images) == 2

    def test_no_images(self):
        """Test data without images."""
        data = {
            "kind": "ConfigMap",
            "data": {"key": "value"}
        }
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
