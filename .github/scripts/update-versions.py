#!/usr/bin/env python
import sys
from pathlib import Path
import re
import time
import asyncio
import traceback
from typing import Optional, Tuple, List, Set, Dict, Any

import aiohttp
import aiofiles
import yaml
from packaging.version import Version, InvalidVersion

CONFIG_PATH = Path(".update-config.yaml")
REPORT_PATH = Path(".update-report.txt")

# Async lock for file writes
FILE_WRITE_LOCK = asyncio.Lock()

# Helm chart concurrency limit to avoid overwhelming DNS and network
# Even though Helm and Docker run sequentially, concurrent Helm requests can still cause issues
HELM_CONCURRENCY_LIMIT = 5

# Helm chart semaphore for rate limiting (will be initialized in main)
HELM_SEMAPHORE: Optional[asyncio.Semaphore] = None

# Per-registry concurrency limits to avoid rate limiting
# These limits are conservative to stay well below API rate limits
REGISTRY_LIMITS = {
    'dockerhub': 3,      # Docker Hub is most restrictive (100 req/6h anonymous)
    'ghcr.io': 10,       # GitHub has generous limits (5000 req/h with token)
    'quay.io': 5,        # Quay is moderate
    'gcr.io': 5,         # GCR is lenient
}
DEFAULT_REGISTRY_LIMIT = 5

# Registry-specific semaphores for rate limiting (will be initialized in main)
REGISTRY_SEMAPHORES: Dict[str, asyncio.Semaphore] = {}

# Compiled regex patterns for version normalization (module-level for performance)
# These patterns convert non-standard version formats to PEP 440 format
PATTERN_P_SUFFIX = re.compile(r'^v?(\d+\.\d+\.\d+)-p(\d+)$')      # v1.24.1-p1 → 1.24.1.post1
PATTERN_DEBIAN_REV = re.compile(r'^v?(\d+\.\d+\.\d+)-(\d+)$')    # v1.24.1-2 → 1.24.1.post2
PATTERN_SIMPLE = re.compile(r'^v?(\d+\.\d+\.\d+)$')              # v1.24.1 → 1.24.1


async def load_yaml(path: Path) -> dict:
    """Load YAML file asynchronously."""
    async with aiofiles.open(path, "r", encoding="utf-8") as f:
        content = await f.read()
        return yaml.safe_load(content)


def normalize_version_string(tag: str) -> str:
    """
    Normalize version tags to PEP 440 format for consistent parsing.

    Handles common non-standard versioning patterns:
    - Docker image patches: v1.24.1-p1 → 1.24.1.post1 (pgbouncer, custom images)
    - Debian revisions: v1.24.1-2 → 1.24.1.post2 (Debian/Ubuntu packages)
    - Simple semver: v1.24.1 → 1.24.1 (strip v prefix)
    - Variants: 1.24.1-alpine → 1.24.1 (extract core, handled by fallback)

    Args:
        tag: Version tag string to normalize

    Returns:
        Normalized version string compatible with PEP 440

    Examples:
        >>> normalize_version_string("v1.24.1-p1")
        '1.24.1.post1'
        >>> normalize_version_string("v1.24.1")
        '1.24.1'
        >>> normalize_version_string("1.24.1-alpine")
        '1.24.1'
    """
    # Fast path 1: -pN suffix (Docker image patches like pgbouncer)
    # Matches: v1.24.1-p1, 1.24.1-p2, etc.
    m = PATTERN_P_SUFFIX.match(tag)
    if m:
        return f'{m.group(1)}.post{m.group(2)}'

    # Fast path 2: -N suffix (Debian package revisions)
    # Matches: v1.24.1-2, 1.24.1-1, etc. (but not variants like -alpine)
    m = PATTERN_DEBIAN_REV.match(tag)
    if m:
        return f'{m.group(1)}.post{m.group(2)}'

    # Fast path 3: Simple semver (no suffix)
    # Matches: v1.24.1, 1.24.1, etc.
    m = PATTERN_SIMPLE.match(tag)
    if m:
        return m.group(1)

    # Fallback: extract core for variants (-alpine, -debian, etc.)
    # This handles tags like 1.24.1-alpine3.19 by extracting just 1.24.1
    tag = tag.lstrip('v')
    core = ''
    for ch in tag:
        if ch.isdigit() or ch == '.':
            core += ch
        else:
            break
    return core


async def retry_on_rate_limit(coro_func, max_retries=3):
    """
    Wrapper to retry async API calls if rate limited (429 error).
    Uses exponential backoff: 2s, 4s, 8s.
    """
    for attempt in range(max_retries):
        try:
            return await coro_func()
        except aiohttp.ClientResponseError as e:
            if e.status == 429:  # Rate limit exceeded
                if attempt < max_retries - 1:
                    wait_time = 2 ** (attempt + 1)  # 2, 4, 8 seconds
                    print(f"  [WARN] Rate limited, retrying in {wait_time}s... (attempt {attempt + 1}/{max_retries})")
                    await asyncio.sleep(wait_time)
                else:
                    print(f"  [ERROR] Rate limit exceeded after {max_retries} attempts")
                    raise
            else:
                raise
        except Exception as e:
            raise
    return None


def build_ignore_lookups(ignore_config: Optional[dict]) -> Tuple[Dict[str, dict], Dict[str, dict]]:
    """
    Build optimized lookup structures for ignore rules with pre-compiled regex patterns.

    Returns:
        (docker_ignore_by_id, helm_ignore_by_name) - O(1) lookup dicts with compiled patterns
    """
    docker_ignore_by_id = {}
    helm_ignore_by_name = {}

    if not ignore_config:
        return docker_ignore_by_id, helm_ignore_by_name

    # Process Docker image ignore rules
    docker_ignores = ignore_config.get("dockerImages", [])
    for ignore_rule in docker_ignores:
        if "id" in ignore_rule:
            # Pre-compile regex patterns for performance
            processed_rule = ignore_rule.copy()

            if "versionPattern" in ignore_rule:
                processed_rule["_compiled_version_pattern"] = re.compile(ignore_rule["versionPattern"])

            if "tagPattern" in ignore_rule:
                processed_rule["_compiled_tag_pattern"] = re.compile(ignore_rule["tagPattern"])

            docker_ignore_by_id[ignore_rule["id"]] = processed_rule

    # Process Helm chart ignore rules
    helm_ignores = ignore_config.get("helmCharts", [])
    for ignore_rule in helm_ignores:
        if "name" in ignore_rule:
            processed_rule = ignore_rule.copy()

            if "versionPattern" in ignore_rule:
                processed_rule["_compiled_version_pattern"] = re.compile(ignore_rule["versionPattern"])

            helm_ignore_by_name[ignore_rule["name"]] = processed_rule

    return docker_ignore_by_id, helm_ignore_by_name


def should_ignore_docker_image(entry: dict, tag: str, docker_ignore_by_id: Dict[str, dict]) -> Tuple[bool, Optional[str]]:
    """
    Check if a Docker image should be ignored based on ignore configuration.

    Args:
        entry: Docker image entry from config
        tag: Current tag of the image
        docker_ignore_by_id: Pre-built lookup dict with compiled regex patterns

    Returns:
        (should_ignore: bool, reason: str)
    """
    if not docker_ignore_by_id:
        return False, None

    # O(1) lookup by ID
    entry_id = entry.get("id")
    if entry_id and entry_id in docker_ignore_by_id:
        ignore_rule = docker_ignore_by_id[entry_id]

        # If there's a versionPattern, don't skip the image entirely
        # The pattern will be used to filter out specific versions during tag selection
        if "versionPattern" not in ignore_rule:
            # No version pattern means ignore all versions of this image
            return True, f"ignored by ID: {ignore_rule['id']}"

        # Check tag pattern if present (uses pre-compiled regex)
        if "_compiled_tag_pattern" in ignore_rule:
            if ignore_rule["_compiled_tag_pattern"].match(tag):
                return True, f"ignored by ID + tag pattern: {ignore_rule['id']}"

    return False, None


def should_ignore_helm_chart(name: str, version: str, helm_ignore_by_name: Dict[str, dict]) -> Tuple[bool, Optional[str]]:
    """
    Check if a Helm chart should be ignored based on ignore configuration.

    Args:
        name: Helm chart name
        version: Current version of the chart
        helm_ignore_by_name: Pre-built lookup dict with compiled regex patterns

    Returns:
        (should_ignore: bool, reason: str)
    """
    if not helm_ignore_by_name:
        return False, None

    # O(1) lookup by name
    if name in helm_ignore_by_name:
        ignore_rule = helm_ignore_by_name[name]

        # Check if there's a version pattern (uses pre-compiled regex)
        if "_compiled_version_pattern" in ignore_rule:
            if ignore_rule["_compiled_version_pattern"].match(version):
                return True, f"ignored by name + version pattern: {name} with version {ignore_rule['versionPattern']}"
        else:
            return True, f"ignored by name: {name}"

    return False, None


def latest_semver(versions: List[str]) -> Optional[str]:
    """
    Find the latest stable semver version from a list.
    Filters out alpha, beta, rc, and pre-release versions.

    Normalizes version strings before parsing to handle non-standard formats.
    """
    valid = []
    for v in versions:
        v_str = str(v)
        # Filter out pre-release versions (alpha, beta, rc)
        v_lower = v_str.lower()
        if any(marker in v_lower for marker in ['alpha', 'beta', 'rc', '-pre', '.pre']):
            continue
        try:
            # Normalize version string before parsing
            normalized = normalize_version_string(v_str)
            if not normalized:
                continue
            parsed = Version(normalized)
            # Also filter out versions marked as pre-release by packaging
            if not parsed.is_prerelease:
                valid.append((parsed, v_str))
        except InvalidVersion:
            continue
    if not valid:
        return None
    valid.sort()
    return valid[-1][1]


def replace_yaml_scalar(text: str, key: str, old: str, new: str) -> Tuple[str, int]:
    """
    Replace a YAML scalar value, handling both quoted and unquoted values.

    Matches patterns like:
      - key: value
      - key: "value"
      - key: 'value'
    """
    # Try to match with optional quotes around the value
    # Pattern: key: "old" or key: 'old' or key: old
    pattern = rf'^(\s*{re.escape(key)}\s*:\s*)(["\']?){re.escape(old)}(["\']?)(.*)$'

    def replacer(match):
        # Preserve the quotes that were around the old value
        prefix = match.group(1)
        open_quote = match.group(2)
        close_quote = match.group(3)
        suffix = match.group(4)
        return f"{prefix}{open_quote}{new}{close_quote}{suffix}"

    new_text, count = re.subn(pattern, replacer, text, count=1, flags=re.MULTILINE)

    if count == 0:
        # Fallback: try simple replacements with different quote styles
        for quote in ['', '"', "'"]:
            fallback = f"{key}: {quote}{old}{quote}"
            if fallback in text:
                tmp = text.replace(fallback, f"{key}: {quote}{new}{quote}", 1)
                if tmp != text:
                    return tmp, 1

    return new_text, count


# ----------------- HELM STUFF -----------------


async def get_latest_helm_chart_version(session: aiohttp.ClientSession, repo_url: str, chart_name: str) -> Optional[str]:
    """Get the latest Helm chart version from a repository."""
    index_url = repo_url.rstrip("/") + "/index.yaml"

    # Use semaphore to limit concurrent Helm chart requests
    async with HELM_SEMAPHORE:
        # Retry logic for transient network errors
        max_retries = 3
        for attempt in range(max_retries):
            try:
                async with session.get(index_url, timeout=aiohttp.ClientTimeout(total=30)) as resp:
                    resp.raise_for_status()
                    content = await resp.text()
                break
            except (asyncio.TimeoutError, aiohttp.ClientError) as e:
                if attempt < max_retries - 1:
                    wait_time = 2 ** attempt  # Exponential backoff: 1s, 2s, 4s
                    error_msg = f"{type(e).__name__}: {e}" if str(e) else type(e).__name__
                    print(f"  [WARN] Helm chart request failed (attempt {attempt + 1}/{max_retries}), retrying in {wait_time}s: {error_msg}")
                    await asyncio.sleep(wait_time)
                else:
                    error_msg = f"{type(e).__name__}: {e}" if str(e) else type(e).__name__
                    print(f"  [ERROR] Helm chart request failed after {max_retries} attempts: {error_msg}")
                    raise

    index = yaml.safe_load(content)
    entries = index.get("entries", {}).get(chart_name, [])
    versions = [e["version"] for e in entries if "version" in e]
    return latest_semver(versions)


async def update_argo_app_chart(file_path: Path, chart_name: str, latest_version: str, dry_run: bool) -> Tuple[bool, Optional[str], Optional[str]]:
    """
    Update spec.source.targetRevision for an Argo CD Application without
    re-dumping the whole YAML. Returns (changed, old, new).
    """
    data = await load_yaml(file_path)

    try:
        source = data["spec"]["source"]
    except (KeyError, TypeError):
        print(f"  [WARN] {file_path} has no spec.source, skipping")
        return False, None, None

    if source.get("chart") != chart_name:
        print(f"  [WARN] {file_path} spec.source.chart != {chart_name}, skipping")
        return False, None, None

    current = str(source.get("targetRevision", ""))
    if not current:
        print(f"  [WARN] {file_path} has empty targetRevision, skipping")
        return False, None, None

    print(f"  {file_path}: current={current}, latest={latest_version}")
    try:
        # Normalize both versions before comparison to handle -pN suffixes, etc.
        latest_normalized = normalize_version_string(latest_version)
        current_normalized = normalize_version_string(current)
        if Version(latest_normalized) <= Version(current_normalized):
            print("  -> up to date")
            return False, None, None
    except InvalidVersion:
        print("  [WARN] Non-semver targetRevision, skipping semver comparison")
        if current == latest_version:
            return False, None, None

    print("  -> updating targetRevision")

    if dry_run:
        return True, current, latest_version

    # Async file write with lock
    async with FILE_WRITE_LOCK:
        async with aiofiles.open(file_path, "r", encoding="utf-8") as f:
            text = await f.read()
        new_text, count = replace_yaml_scalar(text, "targetRevision", current, latest_version)
        if count == 0:
            print(f"  [WARN] Could not replace targetRevision in {file_path} (no matching line), skipping write")
            return False, None, None
        async with aiofiles.open(file_path, "w", encoding="utf-8") as f:
            await f.write(new_text)

    return True, current, latest_version


async def update_kustomize_helm_chart(file_path: Path, chart_name: str, latest_version: str, dry_run: bool) -> Tuple[bool, Optional[str], Optional[str]]:
    """
    Update helmCharts[].version for a given chart in a kustomization.yaml file
    using text-level replacement. Returns (changed, old, new) for the first change.
    """
    data = await load_yaml(file_path)

    charts = data.get("helmCharts")
    if not isinstance(charts, list):
        print(f"  [WARN] {file_path} has no helmCharts list, skipping")
        return False, None, None

    target_current = None

    for c in charts:
        if c.get("name") != chart_name:
            continue
        current = str(c.get("version", ""))
        if not current:
            print(f"  [WARN] {file_path} helmCharts entry for {chart_name} has no version")
            continue

        print(f"  {file_path} ({chart_name}): current={current}, latest={latest_version}")
        try:
            # Normalize both versions before comparison to handle -pN suffixes, etc.
            latest_normalized = normalize_version_string(latest_version)
            current_normalized = normalize_version_string(current)
            if Version(latest_normalized) <= Version(current_normalized):
                print("  -> up to date")
                continue
        except InvalidVersion:
            print("  [WARN] Non-semver version in file, skipping semver comparison")
            if current == latest_version:
                continue

        target_current = current
        break

    if not target_current:
        return False, None, None

    print("  -> updating version")

    if dry_run:
        return True, target_current, latest_version

    # Async file write with lock
    async with FILE_WRITE_LOCK:
        async with aiofiles.open(file_path, "r", encoding="utf-8") as f:
            text = await f.read()
        new_text, count = replace_yaml_scalar(text, "version", target_current, latest_version)
        if count == 0:
            print(f"  [WARN] Could not find 'version: {target_current}' in {file_path} for chart {chart_name}")
            return False, None, None
        async with aiofiles.open(file_path, "w", encoding="utf-8") as f:
            await f.write(new_text)

    return True, target_current, latest_version


async def update_chart_yaml(file_path: Path, chart_name: str, latest_version: str, dry_run: bool) -> Tuple[bool, Optional[str], Optional[str]]:
    """
    Update dependencies[].version for a given chart in a Chart.yaml file
    using text-level replacement. Returns (changed, old, new) for the first change.
    """
    data = await load_yaml(file_path)

    dependencies = data.get("dependencies")
    if not isinstance(dependencies, list):
        print(f"  [WARN] {file_path} has no dependencies list, skipping")
        return False, None, None

    target_current = None

    for dep in dependencies:
        if dep.get("name") != chart_name:
            continue
        current = str(dep.get("version", ""))
        if not current:
            print(f"  [WARN] {file_path} dependencies entry for {chart_name} has no version")
            continue

        print(f"  {file_path} ({chart_name}): current={current}, latest={latest_version}")
        try:
            # Normalize both versions before comparison to handle -pN suffixes, etc.
            latest_normalized = normalize_version_string(latest_version)
            current_normalized = normalize_version_string(current)
            if Version(latest_normalized) <= Version(current_normalized):
                print("  -> up to date")
                continue
        except InvalidVersion:
            print("  [WARN] Non-semver version in file, skipping semver comparison")
            if current == latest_version:
                continue

        target_current = current
        break

    if not target_current:
        return False, None, None

    print("  -> updating version")

    if dry_run:
        return True, target_current, latest_version

    # Async file write with lock
    async with FILE_WRITE_LOCK:
        async with aiofiles.open(file_path, "r", encoding="utf-8") as f:
            text = await f.read()
        new_text, count = replace_yaml_scalar(text, "version", target_current, latest_version)
        if count == 0:
            print(f"  [WARN] Could not find 'version: {target_current}' in {file_path} for chart {chart_name}")
            return False, None, None
        async with aiofiles.open(file_path, "w", encoding="utf-8") as f:
            await f.write(new_text)

    return True, target_current, latest_version


async def process_argo_app(session: aiohttp.ClientSession, app: dict, helm_ignore_by_name: Dict[str, dict], dry_run: bool) -> Tuple[Set[str], List[dict], Optional[str]]:
    """Process a single Argo CD app. Returns (changed_files, helm_changes, errors)."""
    changed_files = set()
    helm_changes = []

    name = app["name"]
    repo_url = app["repoUrl"]
    file_path = Path(app["file"])

    print(f"\n[ARGO APP] {name} in {file_path}")

    try:
        # Check current version to see if ignored
        data = await load_yaml(file_path)
        current_version = ""
        try:
            current_version = str(data["spec"]["source"].get("targetRevision", ""))
        except (KeyError, TypeError):
            pass

        ignored, reason = should_ignore_helm_chart(name, current_version, helm_ignore_by_name)
        if ignored:
            print(f"  [SKIP] {reason}")
            return changed_files, helm_changes, None

        latest = await get_latest_helm_chart_version(session, repo_url, name)
        if not latest:
            print(f"  [WARN] No valid versions found in {repo_url} for {name}")
            return changed_files, helm_changes, None

        changed, old, new = await update_argo_app_chart(file_path, name, latest, dry_run)
        if changed:
            changed_files.add(str(file_path))
            helm_changes.append(
                {
                    "kind": "argoApplication",
                    "name": name,
                    "file": str(file_path),
                    "from": old,
                    "to": new,
                }
            )
    except Exception as e:
        error_msg = f"Failed to process {name}: {type(e).__name__}: {e}"
        print(f"  [ERROR] {error_msg}")
        print(f"  [ERROR] Traceback:\n{traceback.format_exc()}")
        return changed_files, helm_changes, error_msg

    return changed_files, helm_changes, None


async def process_kustomize_chart(session: aiohttp.ClientSession, entry: dict, helm_ignore_by_name: Dict[str, dict], dry_run: bool) -> Tuple[Set[str], List[dict], Optional[str]]:
    """Process a single Kustomize Helm chart. Returns (changed_files, helm_changes, errors)."""
    changed_files = set()
    helm_changes = []

    name = entry["name"]
    repo_url = entry["repoUrl"]

    print(f"\n[KUSTOMIZE] {name}")

    try:
        # For kustomize, we'll check with empty version (can add more sophisticated check if needed)
        ignored, reason = should_ignore_helm_chart(name, "", helm_ignore_by_name)
        if ignored:
            print(f"  [SKIP] {reason}")
            return changed_files, helm_changes, None

        latest = await get_latest_helm_chart_version(session, repo_url, name)
        if not latest:
            print(f"  [WARN] No valid versions found in {repo_url} for {name}")
            return changed_files, helm_changes, None

        for f in entry.get("files", []):
            file_path = Path(f)
            changed, old, new = await update_kustomize_helm_chart(file_path, name, latest, dry_run)
            if changed:
                changed_files.add(str(file_path))
                helm_changes.append(
                    {
                        "kind": "kustomizeHelm",
                        "name": name,
                        "file": str(file_path),
                        "from": old,
                        "to": new,
                    }
                )
    except Exception as e:
        error_msg = f"Failed to process {name}: {type(e).__name__}: {e}"
        print(f"  [ERROR] {error_msg}")
        print(f"  [ERROR] Traceback:\n{traceback.format_exc()}")
        return changed_files, helm_changes, error_msg

    return changed_files, helm_changes, None


async def process_chart_dependency(session: aiohttp.ClientSession, entry: dict, helm_ignore_by_name: Dict[str, dict], dry_run: bool) -> Tuple[Set[str], List[dict], Optional[str]]:
    """Process a single Chart.yaml dependency. Returns (changed_files, helm_changes, errors)."""
    changed_files = set()
    helm_changes = []

    name = entry["name"]
    repo_url = entry["repoUrl"]

    print(f"\n[CHART.YAML] {name}")

    try:
        # Check if chart is ignored
        ignored, reason = should_ignore_helm_chart(name, "", helm_ignore_by_name)
        if ignored:
            print(f"  [SKIP] {reason}")
            return changed_files, helm_changes, None

        latest = await get_latest_helm_chart_version(session, repo_url, name)
        if not latest:
            print(f"  [WARN] No valid versions found in {repo_url} for {name}")
            return changed_files, helm_changes, None

        for f in entry.get("files", []):
            file_path = Path(f)
            changed, old, new = await update_chart_yaml(file_path, name, latest, dry_run)
            if changed:
                changed_files.add(str(file_path))
                helm_changes.append(
                    {
                        "kind": "chartDependency",
                        "name": name,
                        "file": str(file_path),
                        "from": old,
                        "to": new,
                    }
                )
    except Exception as e:
        error_msg = f"Failed to process {name}: {type(e).__name__}: {e}"
        print(f"  [ERROR] {error_msg}")
        print(f"  [ERROR] Traceback:\n{traceback.format_exc()}")
        return changed_files, helm_changes, error_msg

    return changed_files, helm_changes, None


async def update_helm_charts(session: aiohttp.ClientSession, config: dict, helm_ignore_by_name: Dict[str, dict], dry_run: bool) -> Tuple[Set[str], List[dict]]:
    """Update all Helm charts concurrently."""
    changed_files = set()
    helm_changes = []

    argo_apps = config.get("argoApps", [])
    kustomize_charts = config.get("kustomizeHelmCharts", [])
    chart_dependencies = config.get("chartDependencies", [])

    all_tasks = []
    all_tasks.extend([("argo", app) for app in argo_apps])
    all_tasks.extend([("kustomize", chart) for chart in kustomize_charts])
    all_tasks.extend([("chartDep", dep) for dep in chart_dependencies])

    if not all_tasks:
        return changed_files, helm_changes

    # Process Helm charts concurrently using asyncio.gather
    tasks = []
    for task_type, item in all_tasks:
        if task_type == "argo":
            task = process_argo_app(session, item, helm_ignore_by_name, dry_run)
        elif task_type == "kustomize":
            task = process_kustomize_chart(session, item, helm_ignore_by_name, dry_run)
        else:  # chartDep
            task = process_chart_dependency(session, item, helm_ignore_by_name, dry_run)
        tasks.append(task)

    # Gather all results
    results = await asyncio.gather(*tasks, return_exceptions=True)

    # Process results
    for result in results:
        if isinstance(result, Exception):
            print(f"  [ERROR] Unexpected exception not caught by processing function: {type(result).__name__}: {result}")
            print(f"  [ERROR] Traceback:\n{traceback.format_exc()}")
        else:
            files, changes, error = result
            changed_files.update(files)
            helm_changes.extend(changes)
            # Error is already logged in the processing function, no need to print again

    return changed_files, helm_changes


# ----------------- DOCKER STUFF (Docker Hub, semver-aware) -----------------


def parse_image(image_str: str) -> Tuple[str, str]:
    """
    Split 'repo:tag' or 'registry/repo:tag' into (name, tag).
    """
    if ":" not in image_str:
        return image_str, ""
    name, tag = image_str.rsplit(":", 1)
    return name, tag


def extract_semver_core(tag: str) -> Optional[str]:
    """
    Extract a semver-ish core from a tag by taking leading [0-9.] chars.
    """
    core = ""
    for ch in tag:
        if ch.isdigit() or ch == ".":
            core += ch
        else:
            break
    return core or None


def parse_semver_from_tag(tag: str) -> Optional[Version]:
    """
    Parse a version tag into a packaging.version.Version object.

    Uses normalize_version_string() to handle non-standard version formats
    like Docker image patches (-p1) and Debian package revisions (-2).

    Args:
        tag: Version tag string to parse

    Returns:
        Version object if parsing succeeds, None otherwise

    Examples:
        >>> parse_semver_from_tag("v1.24.1-p1")
        <Version('1.24.1.post1')>
        >>> parse_semver_from_tag("1.24.1-alpine")
        <Version('1.24.1')>
    """
    normalized = normalize_version_string(tag)
    if not normalized:
        return None
    try:
        return Version(normalized)
    except InvalidVersion:
        return None


def extract_variant_pattern(tag: str) -> Optional[str]:
    """
    Extract the variant/flavor pattern from a Docker tag.

    Examples:
        18.1-alpine3.22 -> alpine
        8.0.39-debian -> debian
        16.20.2-alpine3.19 -> alpine
        1.2.3-slim-bookworm -> slim
        1.2.3 -> None (no variant)

    Returns the variant type (alpine, debian, slim, etc.) or None if no variant.
    """
    # First extract the version prefix
    core = extract_semver_core(tag)
    if not core:
        return None

    # Get everything after the version
    remainder = tag[len(core):]
    if not remainder:
        return None

    # Remove leading dash if present
    remainder = remainder.lstrip("-")
    if not remainder:
        return None

    # Extract the variant name (first word/identifier)
    # Common patterns: alpine, debian, slim, bookworm, bullseye, etc.
    variant_match = re.match(r"^([a-zA-Z]+)", remainder)
    if variant_match:
        return variant_match.group(1).lower()

    return None


def is_tag_candidate(tag: str, required_variant: Optional[str] = None) -> bool:
    """
    Decide whether a tag is eligible for automatic updates.

    Rules:
      - Allow tags like 'X.Y.Z-b' or 'X.Y.Z-bN' explicitly.
      - Reject tags that contain 'alpha', 'beta', or 'rc' (case-insensitive).
      - If required_variant is set, only accept tags with that variant.
      - Allow everything else (subject to semver parsing).
    """
    if re.match(r"^\d+\.\d+\.\d+-b(\d+)?$", tag):
        return True

    t_lower = tag.lower()
    bad_markers = ["alpha", "beta", "rc"]
    if any(m in t_lower for m in bad_markers):
        return False

    # Check variant matching - variants must match exactly (including None)
    # If current tag has no variant, only accept tags with no variant
    # If current tag has "alpine", only accept tags with "alpine"
    tag_variant = extract_variant_pattern(tag)
    if tag_variant != required_variant:
        return False

    return True


async def list_dockerhub_tags(session: aiohttp.ClientSession, api_repo: str) -> List[str]:
    """
    List tags from Docker Hub.

    Supports authentication via DOCKERHUB_USERNAME and DOCKERHUB_TOKEN environment variables.
    Authentication increases rate limits from 100 req/6h to 200 req/6h (free account).
    """
    import os
    import base64

    url = f"https://registry.hub.docker.com/v2/repositories/{api_repo}/tags?page_size=100"
    tags: List[str] = []
    headers = {}

    # Check for Docker Hub authentication
    dockerhub_username = os.environ.get("DOCKERHUB_USERNAME")
    dockerhub_token = os.environ.get("DOCKERHUB_TOKEN") or os.environ.get("DOCKERHUB_PASSWORD")

    if dockerhub_username and dockerhub_token:
        # Use HTTP Basic Auth for Docker Hub API
        credentials = f"{dockerhub_username}:{dockerhub_token}"
        encoded = base64.b64encode(credentials.encode()).decode()
        headers["Authorization"] = f"Basic {encoded}"

    while url:
        # Retry logic for transient network errors
        max_retries = 3
        for attempt in range(max_retries):
            try:
                async with session.get(url, headers=headers, timeout=aiohttp.ClientTimeout(total=30)) as resp:
                    resp.raise_for_status()
                    data = await resp.json()
                    for r in data.get("results", []):
                        name = r.get("name")
                        if name:
                            tags.append(name)
                    url = data.get("next")
                break
            except (asyncio.TimeoutError, aiohttp.ClientError) as e:
                if attempt < max_retries - 1:
                    wait_time = 2 ** attempt  # Exponential backoff: 1s, 2s, 4s
                    error_msg = f"{type(e).__name__}: {e}" if str(e) else type(e).__name__
                    print(f"  [WARN] Docker Hub request failed (attempt {attempt + 1}/{max_retries}), retrying in {wait_time}s: {error_msg}")
                    await asyncio.sleep(wait_time)
                else:
                    error_msg = f"{type(e).__name__}: {e}" if str(e) else type(e).__name__
                    print(f"  [ERROR] Docker Hub request failed after {max_retries} attempts: {error_msg}")
                    raise

    return tags


async def list_ghcr_tags(session: aiohttp.ClientSession, repository: str) -> List[str]:
    """
    List tags from GitHub Container Registry (ghcr.io).

    Uses Docker Registry HTTP API V2 with token authentication.
    Handles pagination to fetch all tags (API returns max 100 per request).
    For public images, works without authentication.
    For private images or higher rate limits, set GITHUB_TOKEN environment variable.

    Note: GITHUB_TOKEN must be base64 encoded for ghcr.io authentication.
    """
    import os
    import base64

    base_url = f"https://ghcr.io/v2/{repository}/tags/list"
    github_token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")

    headers = {}
    if github_token:
        # ghcr.io requires base64-encoded GITHUB_TOKEN
        encoded_token = base64.b64encode(github_token.encode()).decode()
        headers["Authorization"] = f"Bearer {encoded_token}"

    all_tags = []
    url = f"{base_url}?n=1000"  # Request up to 1000 tags per page

    try:
        while url:
            # Retry logic for transient network errors
            max_retries = 3
            for attempt in range(max_retries):
                try:
                    async with session.get(url, headers=headers, timeout=aiohttp.ClientTimeout(total=30)) as resp:
                        resp.raise_for_status()
                        data = await resp.json()
                        tags = data.get("tags", [])
                        all_tags.extend(tags)

                        # Check for pagination link in Link header
                        link_header = resp.headers.get("Link", "")
                        if link_header and 'rel="next"' in link_header:
                            # Extract next URL from Link header
                            # Format: </v2/repo/tags/list?n=100&last=tag>; rel="next"
                            match = re.search(r'<(/v2/[^>]+)>;\s*rel="next"', link_header)
                            if match:
                                url = f"https://ghcr.io{match.group(1)}"
                            else:
                                break
                        else:
                            break
                    break
                except (asyncio.TimeoutError, aiohttp.ClientError) as e:
                    if attempt < max_retries - 1:
                        wait_time = 2 ** attempt
                        error_msg = f"{type(e).__name__}: {e}" if str(e) else type(e).__name__
                        print(f"  [WARN] GHCR request failed (attempt {attempt + 1}/{max_retries}), retrying in {wait_time}s: {error_msg}")
                        await asyncio.sleep(wait_time)
                    else:
                        raise

        return all_tags
    except Exception as e:
        print(f"  [WARN] Failed to fetch ghcr.io tags for {repository}: {e}")
        return []


async def list_quay_tags(session: aiohttp.ClientSession, repository: str) -> List[str]:
    """List tags from Quay.io."""
    url = f"https://quay.io/api/v1/repository/{repository}/tag/?limit=100&page=1"
    tags: List[str] = []

    try:
        while url:
            # Retry logic for transient network errors
            max_retries = 3
            for attempt in range(max_retries):
                try:
                    async with session.get(url, timeout=aiohttp.ClientTimeout(total=30)) as resp:
                        resp.raise_for_status()
                        data = await resp.json()

                        for tag_data in data.get("tags", []):
                            name = tag_data.get("name")
                            if name:
                                tags.append(name)

                        # Check if there are more pages
                        if data.get("has_additional"):
                            page = data.get("page", 1) + 1
                            url = f"https://quay.io/api/v1/repository/{repository}/tag/?limit=100&page={page}"
                        else:
                            url = None
                    break
                except (asyncio.TimeoutError, aiohttp.ClientError) as e:
                    if attempt < max_retries - 1:
                        wait_time = 2 ** attempt
                        error_msg = f"{type(e).__name__}: {e}" if str(e) else type(e).__name__
                        print(f"  [WARN] Quay.io request failed (attempt {attempt + 1}/{max_retries}), retrying in {wait_time}s: {error_msg}")
                        await asyncio.sleep(wait_time)
                    else:
                        raise

        return tags
    except Exception as e:
        print(f"  [WARN] Failed to fetch quay.io tags for {repository}: {e}")
        return []


async def list_gcr_tags(session: aiohttp.ClientSession, repository: str) -> List[str]:
    """
    List tags from Google Container Registry (gcr.io).

    Uses Docker Registry HTTP API V2.
    Note: Only works for public images.
    """
    # gcr.io uses Docker Registry V2 API
    url = f"https://gcr.io/v2/{repository}/tags/list"

    try:
        # Retry logic for transient network errors
        max_retries = 3
        for attempt in range(max_retries):
            try:
                async with session.get(url, timeout=aiohttp.ClientTimeout(total=30)) as resp:
                    if resp.status == 401:
                        print(f"  [WARN] gcr.io repository {repository} requires authentication")
                        return []
                    resp.raise_for_status()
                    data = await resp.json()
                    return data.get("tags", [])
            except (asyncio.TimeoutError, aiohttp.ClientError) as e:
                if attempt < max_retries - 1:
                    wait_time = 2 ** attempt
                    error_msg = f"{type(e).__name__}: {e}" if str(e) else type(e).__name__
                    print(f"  [WARN] GCR request failed (attempt {attempt + 1}/{max_retries}), retrying in {wait_time}s: {error_msg}")
                    await asyncio.sleep(wait_time)
                else:
                    raise
    except Exception as e:
        print(f"  [WARN] Failed to fetch gcr.io tags for {repository}: {e}")
        return []


async def list_registry_tags(session: aiohttp.ClientSession, registry: str, repository: str) -> List[str]:
    """
    List tags from any container registry.

    Supports:
    - dockerhub (Docker Hub)
    - ghcr.io (GitHub Container Registry)
    - quay.io (Quay.io)
    - gcr.io (Google Container Registry)
    - generic Docker Registry V2 API compatible registries
    """
    if registry == "dockerhub":
        return await list_dockerhub_tags(session, repository)
    elif registry == "ghcr.io":
        return await list_ghcr_tags(session, repository)
    elif registry == "quay.io":
        return await list_quay_tags(session, repository)
    elif registry == "gcr.io":
        return await list_gcr_tags(session, repository)
    else:
        # Try generic Docker Registry V2 API
        print(f"  [INFO] Trying generic Docker Registry V2 API for {registry}")
        url = f"https://{registry}/v2/{repository}/tags/list"
        try:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                if resp.status == 401:
                    print(f"  [WARN] Registry {registry} requires authentication")
                    return []
                resp.raise_for_status()
                data = await resp.json()
                return data.get("tags", [])
        except Exception as e:
            print(f"  [WARN] Failed to fetch tags from {registry}: {e}")
            return []


async def find_best_tags_for_same_major(session: aiohttp.ClientSession, registry: str, repository: str, current_tag: str, semaphore: Optional[asyncio.Semaphore] = None, entry: Optional[dict] = None, docker_ignore_by_id: Optional[Dict[str, dict]] = None) -> Tuple[Optional[str], Optional[Version], Optional[str], Optional[Version]]:
    """
    Find the best tags for the same major version.

    Args:
        session: The aiohttp client session
        registry: The container registry (dockerhub, ghcr.io, etc.)
        repository: The repository path
        current_tag: The current tag to compare against
        semaphore: Optional semaphore for rate limiting
        entry: Docker image entry (for ignore pattern matching)
        ignore_config: Ignore configuration (for version pattern filtering)

    Returns:
        Tuple of (best_same_tag, best_same_ver, best_any_tag, best_any_ver)
    """
    current_ver = parse_semver_from_tag(current_tag)
    if current_ver is None:
        print(f"  [WARN] Cannot parse current tag '{current_tag}' as semver, skipping semver-based updates")
        return None, None, None, None

    # Extract variant from current tag to preserve it
    current_variant = extract_variant_pattern(current_tag)
    if current_variant:
        print(f"  [INFO] Detected image variant: {current_variant} (will only consider {current_variant} tags)")

    # Use semaphore if provided for rate limiting
    if semaphore:
        async with semaphore:
            tags = await list_registry_tags(session, registry, repository)
    else:
        tags = await list_registry_tags(session, registry, repository)

    if not tags:
        print(f"  [WARN] No tags found in registry {registry} for repo {repository}")
        return None, None, None, None

    # Filter tags based on versionPattern in ignore rules (using pre-compiled regex)
    if entry and docker_ignore_by_id:
        entry_id = entry.get("id")
        if entry_id and entry_id in docker_ignore_by_id:
            ignore_rule = docker_ignore_by_id[entry_id]
            if "_compiled_version_pattern" in ignore_rule:
                compiled_pattern = ignore_rule["_compiled_version_pattern"]
                original_count = len(tags)
                tags = [t for t in tags if not compiled_pattern.match(t)]
                filtered_count = original_count - len(tags)
                if filtered_count > 0:
                    print(f"  [INFO] Filtered out {filtered_count} tags matching versionPattern: {ignore_rule['versionPattern']}")

    same_major: List[Tuple[Version, str]] = []
    all_versions: List[Tuple[Version, str]] = []

    for t in tags:
        # Filter by variant if current tag has one
        if not is_tag_candidate(t, required_variant=current_variant):
            continue

        v = parse_semver_from_tag(t)
        if v is None:
            continue
        all_versions.append((v, t))
        if v.major == current_ver.major:
            same_major.append((v, t))

    # Only fall back to non-variant tags if NO tags found with variant
    # (indicates variant detection might be wrong)
    if not all_versions and current_variant:
        print(f"  [INFO] No tags found with variant '{current_variant}', retrying without variant filter...")
        all_versions = []
        same_major = []
        for t in tags:
            if not is_tag_candidate(t, required_variant=None):
                continue
            v = parse_semver_from_tag(t)
            if v is None:
                continue
            all_versions.append((v, t))
            if v.major == current_ver.major:
                same_major.append((v, t))

    if not all_versions:
        variant_note = f" with variant '{current_variant}'" if current_variant else ""
        print(f"  [WARN] No semver-parsable tags{variant_note} in {registry} repo {repository}")
        return None, None, None, None

    best_any_ver, best_any_tag = max(all_versions, key=lambda x: x[0])

    if same_major:
        best_same_ver, best_same_tag = max(same_major, key=lambda x: x[0])
    else:
        best_same_ver, best_same_tag = None, None

    return best_same_tag, best_same_ver, best_any_tag, best_any_ver


async def update_single_docker_image(session: aiohttp.ClientSession, entry: dict, docker_ignore_by_id: Dict[str, dict], dry_run: bool) -> Tuple[bool, Optional[str], Optional[str], Optional[dict]]:
    """Update a single Docker image."""
    try:
        registry = entry.get("registry", "dockerhub")
        repository = entry["repository"]
        file_path = Path(entry["file"])
        yaml_path = entry["yamlPath"]

        print(f"\n[DOCKER] {entry['id']} in {file_path}")
        print(f"  Registry: {registry}")
        print(f"  Repository: {repository}")

        data = await load_yaml(file_path)

        # follow yamlPath to get current image string
        cur = data
        for key in yaml_path:
            cur = cur[key]
        image_str = str(cur)

        image_name, current_tag = parse_image(image_str)
        if not current_tag:
            print(f"  [WARN] No tag found in image '{image_str}', skipping")
            return False, None, None, None

        print(f"  Current image: {image_str}")

        # Check if this image should be ignored
        ignored, reason = should_ignore_docker_image(entry, current_tag, docker_ignore_by_id)
        if ignored:
            print(f"  [SKIP] {reason}")
            return False, None, None, None

        # Get registry-specific semaphore for rate limiting
        semaphore = REGISTRY_SEMAPHORES.get(registry)

        best_same_tag, best_same_ver, best_any_tag, best_any_ver = await find_best_tags_for_same_major(
            session, registry, repository, current_tag, semaphore, entry, docker_ignore_by_id
        )

        current_ver = parse_semver_from_tag(current_tag)
        major_available = None
        if current_ver and best_any_ver and best_any_ver.major > current_ver.major:
            # Check if the best_any_tag matches versionPattern (should be ignored, using pre-compiled regex)
            should_skip_major = False
            entry_id = entry.get("id")
            if docker_ignore_by_id and entry_id and entry_id in docker_ignore_by_id:
                ignore_rule = docker_ignore_by_id[entry_id]
                if "_compiled_version_pattern" in ignore_rule:
                    if ignore_rule["_compiled_version_pattern"].match(best_any_tag):
                        print(
                            f"  [INFO] Skipping major upgrade report: {best_any_tag} "
                            f"matches versionPattern {ignore_rule['versionPattern']}"
                        )
                        should_skip_major = True

            if not should_skip_major:
                print(
                    f"  [INFO] New major available in {repository}: {best_any_tag} "
                    f"(current major {current_ver.major}, new major {best_any_ver.major})"
                )
                major_available = {
                    "id": entry["id"],
                    "current": current_tag,
                    "available": best_any_tag,
                    "current_major": current_ver.major,
                    "new_major": best_any_ver.major,
                }

        if not best_same_tag or not best_same_ver or current_ver is None:
            print("  [INFO] No suitable same-major update found, skipping")
            return False, None, None, major_available

        if best_same_ver <= current_ver:
            print("  -> already at latest version for this major")
            return False, None, None, major_available

        new_image = f"{image_name}:{best_same_tag}"
        print(f"  -> updating image to {new_image}")

        if dry_run:
            return True, image_str, new_image, major_available

        # Async file write with lock
        async with FILE_WRITE_LOCK:
            async with aiofiles.open(file_path, "r", encoding="utf-8") as f:
                text = await f.read()
            new_text, count = replace_yaml_scalar(text, "image", image_str, new_image)
            if count == 0:
                print(f"  [WARN] Could not replace image '{image_str}' in {file_path}")
                return False, None, None, major_available
            async with aiofiles.open(file_path, "w", encoding="utf-8") as f:
                await f.write(new_text)

        return True, image_str, new_image, major_available
    except Exception as e:
        print(f"  [ERROR] Exception in update_single_docker_image for {entry.get('id', 'unknown')}: {type(e).__name__}: {e}")
        print(f"  [ERROR] Traceback: {traceback.format_exc()}")
        raise


async def update_docker_images(session: aiohttp.ClientSession, config: dict, docker_ignore_by_id: Dict[str, dict], dry_run: bool) -> Tuple[Set[str], List[dict], List[dict]]:
    """Update all Docker images concurrently."""
    changed_files = set()
    docker_changes = []
    major_updates = []

    entries = config.get("dockerImages", [])

    if not entries:
        return changed_files, docker_changes, major_updates

    # Process images concurrently using asyncio.gather
    tasks = [update_single_docker_image(session, entry, docker_ignore_by_id, dry_run) for entry in entries]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    # Process results
    for idx, result in enumerate(results):
        if isinstance(result, Exception):
            # Exception was already logged in update_single_docker_image with full details
            # This is just a final note that processing failed for this entry
            print(f"  [ERROR] Skipping {entries[idx]['id']} due to exception (see details above)")
        else:
            changed, old, new, major_available = result
            if changed:
                changed_files.add(str(entries[idx]["file"]))
                docker_changes.append(
                    {
                        "id": entries[idx]["id"],
                        "file": entries[idx]["file"],
                        "from": old,
                        "to": new,
                    }
                )
            if major_available:
                major_updates.append(major_available)

    return changed_files, docker_changes, major_updates


# ----------------- REPORT -----------------


async def write_report(helm_changes: List[dict], docker_changes: List[dict], major_updates: List[dict]):
    """
    Write a human-readable summary to .update-report.txt.
    """
    if not helm_changes and not docker_changes and not major_updates:
        if REPORT_PATH.exists():
            REPORT_PATH.unlink()
        return

    lines = []
    total_helm = len(helm_changes)
    total_docker = len(docker_changes)
    total_major = len(major_updates)

    lines.append("Update summary")
    lines.append("================")
    lines.append(f"Helm charts updated: {total_helm}")
    lines.append(f"Docker images updated: {total_docker}")
    lines.append(f"Major versions available: {total_major}")
    lines.append("")

    if helm_changes:
        lines.append("Helm chart updates:")
        for c in helm_changes:
            lines.append(
                f"- {c['name']} ({c['kind']}) {c['from']} → {c['to']}  [{c['file']}]"
            )
        lines.append("")

    if docker_changes:
        lines.append("Docker image updates:")
        for c in docker_changes:
            lines.append(
                f"- {c['id']}: {c['from']} → {c['to']}  [{c['file']}]"
            )
        lines.append("")

    if major_updates:
        lines.append("⚠️ Major version upgrades available (not auto-updated):")
        for m in major_updates:
            lines.append(
                f"- {m['id']}: {m['current']} → {m['available']} "
                f"(major {m['current_major']} → {m['new_major']})"
            )
        lines.append("")

    async with aiofiles.open(REPORT_PATH, "w", encoding="utf-8") as f:
        await f.write("\n".join(lines))


# ----------------- MAIN -----------------


async def async_main():
    """Main async function."""
    start_time = time.time()

    if not CONFIG_PATH.exists():
        print("Config file .update-config.yaml not found", file=sys.stderr)
        return 1

    dry_run = "--dry-run" in sys.argv

    config = await load_yaml(CONFIG_PATH)
    ignore_config = config.get("ignore")

    # Build optimized ignore lookups with pre-compiled regex patterns
    docker_ignore_by_id, helm_ignore_by_name = build_ignore_lookups(ignore_config)

    # Initialize registry-specific semaphores
    global REGISTRY_SEMAPHORES, HELM_SEMAPHORE

    # Initialize Helm chart semaphore for concurrency control
    HELM_SEMAPHORE = asyncio.Semaphore(HELM_CONCURRENCY_LIMIT)

    # Initialize Docker registry semaphores
    REGISTRY_SEMAPHORES = {
        registry: asyncio.Semaphore(limit)
        for registry, limit in REGISTRY_LIMITS.items()
    }

    # Check Docker Hub authentication and adjust limits
    import os
    dockerhub_username = os.environ.get("DOCKERHUB_USERNAME", "").strip()
    dockerhub_token = os.environ.get("DOCKERHUB_TOKEN", "").strip() or os.environ.get("DOCKERHUB_PASSWORD", "").strip()
    dockerhub_authenticated = bool(dockerhub_username and dockerhub_token)

    if dockerhub_authenticated:
        print("Docker Hub: Authenticated (200 req/6h rate limit)")
        # Increase Docker Hub concurrency limit when authenticated
        REGISTRY_LIMITS['dockerhub'] = 5
        REGISTRY_SEMAPHORES['dockerhub'] = asyncio.Semaphore(5)
    else:
        print("Docker Hub: Anonymous (100 req/6h rate limit)")
        print("  Tip: Set DOCKERHUB_USERNAME and DOCKERHUB_TOKEN to increase limits")

    if ignore_config:
        print("Ignore rules loaded:")
        docker_ignore_rules = ignore_config.get("dockerImages", [])
        if docker_ignore_rules:
            print(f"  Docker images: {len(docker_ignore_rules)} rule(s)")
        if ignore_config.get("helmCharts"):
            print(f"  Helm charts: {len(ignore_config.get('helmCharts', []))} rule(s)")

    if dry_run:
        print("Running in dry-run mode (no changes will be made)")

    changed_files = set()

    # Create session with connection limits to avoid overwhelming network
    connector = aiohttp.TCPConnector(
        limit=30,  # Total concurrent connections
        limit_per_host=10,  # Max concurrent connections per host
        ttl_dns_cache=300  # Cache DNS for 5 minutes
    )
    async with aiohttp.ClientSession(connector=connector) as session:
        # Run Helm and Docker updates sequentially to reduce network stress
        # Parallel execution caused too many timeouts requiring retries that
        # negated the performance benefit. Sequential is more reliable.
        helm_start = time.time()
        helm_changed_files, helm_changes = await update_helm_charts(session, config, helm_ignore_by_name, dry_run=dry_run)
        helm_duration = time.time() - helm_start

        docker_start = time.time()
        docker_changed_files, docker_changes, major_updates = await update_docker_images(session, config, docker_ignore_by_id, dry_run=dry_run)
        docker_duration = time.time() - docker_start

        changed_files |= helm_changed_files
        changed_files |= docker_changed_files

    # Write report (for CI/Telegram, etc.)
    if not dry_run:
        await write_report(helm_changes, docker_changes, major_updates)

    # Performance summary
    total_duration = time.time() - start_time
    total_helm = len(config.get('argoApps', [])) + len(config.get('kustomizeHelmCharts', [])) + len(config.get('chartDependencies', []))
    total_docker = len(config.get('dockerImages', []))
    print(f"\n{'='*60}")
    print(f"Performance Summary:")
    print(f"  Helm charts: {helm_duration:.2f}s ({total_helm} charts)")
    print(f"  Docker images: {docker_duration:.2f}s ({total_docker} images)")
    print(f"  Total time: {total_duration:.2f}s")
    print(f"{'='*60}")

    if changed_files:
        print("\nChanged files:")
        for f in sorted(changed_files):
            print(f"  - {f}")
    else:
        print("\nNo changes detected.")

    return 0


def main():
    """Entry point that runs the async main function."""
    return asyncio.run(async_main())


if __name__ == "__main__":
    sys.exit(main())
