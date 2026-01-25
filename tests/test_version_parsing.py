"""Tests for version parsing and normalization functions."""

from importlib.machinery import SourceFileLoader
from importlib.util import module_from_spec, spec_from_loader
from pathlib import Path


# Load update-versions.py as a module (it has a hyphen in the name)
def load_update_versions():
    script_path = Path(__file__).parent.parent / ".github" / "scripts" / "update-versions.py"
    loader = SourceFileLoader("update_versions", str(script_path))
    spec = spec_from_loader("update_versions", loader)
    module = module_from_spec(spec)
    loader.exec_module(module)
    return module


update_versions = load_update_versions()


class TestNormalizeVersionString:
    """Tests for normalize_version_string function."""

    def test_simple_semver(self):
        """Test simple semver versions."""
        assert update_versions.normalize_version_string("1.2.3") == "1.2.3"
        assert update_versions.normalize_version_string("10.20.30") == "10.20.30"

    def test_v_prefix(self):
        """Test versions with v prefix."""
        assert update_versions.normalize_version_string("v1.2.3") == "1.2.3"
        assert update_versions.normalize_version_string("v10.20.30") == "10.20.30"

    def test_p_suffix(self):
        """Test Docker image patch versions (-pN suffix)."""
        assert update_versions.normalize_version_string("1.24.1-p1") == "1.24.1.post1"
        assert update_versions.normalize_version_string("v1.24.1-p2") == "1.24.1.post2"
        assert update_versions.normalize_version_string("1.0.0-p10") == "1.0.0.post10"

    def test_debian_revision(self):
        """Test Debian package revision format (-N suffix)."""
        assert update_versions.normalize_version_string("1.24.1-2") == "1.24.1.post2"
        assert update_versions.normalize_version_string("v1.24.1-1") == "1.24.1.post1"

    def test_variant_suffix(self):
        """Test versions with variant suffixes like -alpine."""
        assert update_versions.normalize_version_string("1.24.1-alpine") == "1.24.1"
        assert update_versions.normalize_version_string("1.24.1-alpine3.19") == "1.24.1"
        assert update_versions.normalize_version_string("1.24.1-debian") == "1.24.1"
        assert update_versions.normalize_version_string("1.24.1-slim-bookworm") == "1.24.1"

    def test_empty_string(self):
        """Test empty string returns empty."""
        assert update_versions.normalize_version_string("") == ""

    def test_no_version(self):
        """Test strings without version numbers."""
        assert update_versions.normalize_version_string("latest") == ""
        assert update_versions.normalize_version_string("alpine") == ""


class TestLatestSemver:
    """Tests for latest_semver function."""

    def test_basic_versions(self):
        """Test finding latest from basic versions."""
        versions = ["1.0.0", "1.1.0", "1.2.0", "2.0.0"]
        assert update_versions.latest_semver(versions) == "2.0.0"

    def test_with_v_prefix(self):
        """Test versions with v prefix."""
        versions = ["v1.0.0", "v1.1.0", "v2.0.0"]
        assert update_versions.latest_semver(versions) == "v2.0.0"

    def test_filters_prerelease(self):
        """Test that alpha/beta/rc versions are filtered out."""
        versions = ["1.0.0", "1.1.0", "2.0.0-alpha", "2.0.0-beta", "2.0.0-rc1"]
        assert update_versions.latest_semver(versions) == "1.1.0"

    def test_empty_list(self):
        """Test empty list returns None."""
        assert update_versions.latest_semver([]) is None

    def test_only_prerelease(self):
        """Test list with only prerelease versions returns None."""
        versions = ["1.0.0-alpha", "1.0.0-beta", "1.0.0-rc1"]
        assert update_versions.latest_semver(versions) is None

    def test_mixed_formats(self):
        """Test mixed version formats."""
        versions = ["1.0.0", "v1.1.0", "1.2.0-p1", "1.3.0"]
        assert update_versions.latest_semver(versions) == "1.3.0"


class TestExtractVariantPattern:
    """Tests for extract_variant_pattern function."""

    def test_alpine_variant(self):
        """Test alpine variant extraction."""
        assert update_versions.extract_variant_pattern("18.1-alpine3.22") == "alpine"
        assert update_versions.extract_variant_pattern("1.24.1-alpine") == "alpine"

    def test_debian_variant(self):
        """Test debian variant extraction."""
        assert update_versions.extract_variant_pattern("8.0.39-debian") == "debian"

    def test_slim_variant(self):
        """Test slim variant extraction."""
        assert update_versions.extract_variant_pattern("1.2.3-slim-bookworm") == "slim"

    def test_no_variant(self):
        """Test versions without variants."""
        assert update_versions.extract_variant_pattern("1.2.3") is None
        assert update_versions.extract_variant_pattern("18.1") is None

    def test_invalid_input(self):
        """Test invalid inputs."""
        assert update_versions.extract_variant_pattern("") is None
        assert update_versions.extract_variant_pattern("latest") is None


class TestIsTagCandidate:
    """Tests for is_tag_candidate function."""

    def test_accepts_valid_tags(self):
        """Test that valid tags are accepted."""
        assert update_versions.is_tag_candidate("1.2.3") is True
        assert update_versions.is_tag_candidate("18.1") is True

    def test_rejects_prerelease(self):
        """Test that prerelease tags are rejected."""
        assert update_versions.is_tag_candidate("1.0.0-alpha") is False
        assert update_versions.is_tag_candidate("1.0.0-beta1") is False
        assert update_versions.is_tag_candidate("1.0.0-rc1") is False

    def test_accepts_b_suffix(self):
        """Test that -b suffix (build) is accepted."""
        assert update_versions.is_tag_candidate("1.2.3-b") is True
        assert update_versions.is_tag_candidate("1.2.3-b1") is True

    def test_variant_matching(self):
        """Test variant matching."""
        # With required variant
        assert update_versions.is_tag_candidate("1.2.3-alpine", required_variant="alpine") is True
        assert update_versions.is_tag_candidate("1.2.3-debian", required_variant="alpine") is False
        assert update_versions.is_tag_candidate("1.2.3", required_variant="alpine") is False

        # Without required variant
        assert update_versions.is_tag_candidate("1.2.3", required_variant=None) is True
        assert update_versions.is_tag_candidate("1.2.3-alpine", required_variant=None) is False


class TestParseImage:
    """Tests for parse_image function."""

    def test_simple_image(self):
        """Test simple image without tag."""
        name, tag = update_versions.parse_image("nginx")
        assert name == "nginx"
        assert tag == ""

    def test_image_with_tag(self):
        """Test image with tag."""
        name, tag = update_versions.parse_image("nginx:1.24.0")
        assert name == "nginx"
        assert tag == "1.24.0"

    def test_image_with_registry(self):
        """Test image with registry prefix."""
        name, tag = update_versions.parse_image("ghcr.io/owner/repo:v1.0.0")
        assert name == "ghcr.io/owner/repo"
        assert tag == "v1.0.0"

    def test_image_with_port(self):
        """Test image with registry port."""
        name, tag = update_versions.parse_image("localhost:5000/myimage:latest")
        assert name == "localhost:5000/myimage"
        assert tag == "latest"
