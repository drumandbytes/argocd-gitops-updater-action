#!/usr/bin/env python
"""
Auto-discover Helm charts and Docker images in the repository
and generate/update .update-config.yaml

This async version uses:
- asyncio for concurrent file operations
- aiofiles for non-blocking file I/O
- Concurrent processing for faster discovery
"""

import asyncio
import os
import sys
from io import StringIO
from pathlib import Path

import aiofiles
import yaml
from ruamel.yaml import YAML
from ruamel.yaml.comments import CommentedMap

# Round-trip mode (the ruamel.yaml default) preserves comments, key order,
# and blank lines on anything not explicitly modified - this is only used
# for .update-config.yaml itself (the file this script rewrites), not the
# Application/kustomization/Chart.yaml files it only ever reads.
_ROUNDTRIP_YAML = YAML()
_ROUNDTRIP_YAML.indent(mapping=2, sequence=4, offset=2)
_ROUNDTRIP_YAML.width = 4096  # don't wrap long values (chart repo URLs, etc.)
_ROUNDTRIP_YAML.preserve_quotes = True


def load_yaml_roundtrip(content: str) -> CommentedMap | None:
    return _ROUNDTRIP_YAML.load(content)


def dump_yaml_roundtrip(data) -> str:
    buffer = StringIO()
    _ROUNDTRIP_YAML.dump(data, buffer)
    return buffer.getvalue()


async def load_yaml_safe(path: Path) -> dict | None:
    """Load YAML file asynchronously, return None if it fails or isn't valid YAML."""
    try:
        async with aiofiles.open(path, encoding="utf-8") as f:
            content = await f.read()
            return yaml.safe_load(content)
    except Exception:
        return None


def should_ignore_docker_image(entry: dict, ignore_config: dict | None) -> tuple[bool, str | None]:
    """
    Check if a Docker image should be ignored based on ignore configuration.
    Returns (should_ignore: bool, reason: str)
    """
    if not ignore_config:
        return False, None

    docker_ignores = ignore_config.get("dockerImages", [])

    for ignore_rule in docker_ignores:
        # Check by ID
        if "id" in ignore_rule and ignore_rule["id"] == entry.get("id"):
            return True, f"ignored by ID: {ignore_rule['id']}"

        # Check by repository
        if "repository" in ignore_rule and ignore_rule["repository"] == entry.get("repository"):
            return True, f"ignored by repository: {ignore_rule['repository']}"

    return False, None


def should_ignore_helm_chart(name: str, ignore_config: dict | None) -> tuple[bool, str | None]:
    """
    Check if a Helm chart should be ignored based on ignore configuration.
    Returns (should_ignore: bool, reason: str)
    """
    if not ignore_config:
        return False, None

    helm_ignores = ignore_config.get("helmCharts", [])

    for ignore_rule in helm_ignores:
        # Check by name
        if "name" in ignore_rule and ignore_rule["name"] == name:
            return True, f"ignored by name: {name}"

    return False, None


async def discover_argo_apps(root: Path) -> list[dict]:
    """
    Find all Argo CD Application resources with Helm charts.
    Returns list of {name, repoUrl, file}
    """
    yaml_files = list(root.rglob("*.yaml"))

    # Process files concurrently. return_exceptions=True so one malformed
    # manifest can't crash discovery for every other file in the repo -
    # process_argo_app_file already turns expected bad-input shapes into
    # None, but this is the backstop for anything it doesn't anticipate.
    tasks = [process_argo_app_file(yaml_file, root) for yaml_file in yaml_files]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    apps = []
    for yaml_file, result in zip(yaml_files, results, strict=True):
        if isinstance(result, Exception):
            print(f"  [WARN] Failed to process {yaml_file}: {type(result).__name__}: {result}")
        elif result is not None:
            apps.append(result)
    return sorted(apps, key=lambda x: x["name"])


def _find_helm_source(spec: dict) -> dict | None:
    """
    Find a Helm chart source on an Argo CD Application spec, checking both
    the legacy single-source shape (spec.source) and the multi-source shape
    (spec.sources[]) - a real Application only ever has one or the other,
    never both, per the Argo CD API.
    """
    if not isinstance(spec, dict):
        # A manifest with a present-but-null `spec:` parses to None here,
        # not a missing key - data["spec"] doesn't raise KeyError for that,
        # so this can't rely on the caller's except (KeyError, TypeError)
        # alone. Guarding here stops the AttributeError from spec.get(...)
        # at its source instead.
        return None
    candidates = []
    single = spec.get("source")
    if isinstance(single, dict):
        candidates.append(single)
    multi = spec.get("sources")
    if isinstance(multi, list):
        candidates.extend(s for s in multi if isinstance(s, dict))

    for source in candidates:
        if source.get("chart") and source.get("repoURL"):
            return source
    return None


async def process_argo_app_file(yaml_file: Path, root: Path) -> dict | None:
    """Process a single YAML file to check if it's an Argo CD Application."""
    data = await load_yaml_safe(yaml_file)
    if not data:
        return None

    # Check if it's an Argo CD Application
    if data.get("kind") != "Application":
        return None

    try:
        source = _find_helm_source(data["spec"])
        if source is None:
            return None

        chart = source["chart"]
        repo_url = source["repoURL"]

        # Only include Helm chart repos (URLs starting with http/https)
        # Skip git repositories (ending with .git)
        if not repo_url.startswith("http"):
            return None
        if repo_url.endswith(".git"):
            return None

        return {"name": chart, "repoUrl": repo_url, "file": str(yaml_file.relative_to(root))}
    except (KeyError, TypeError):
        return None


async def discover_kustomize_helm_charts(root: Path) -> list[dict]:
    """
    Find all kustomization.yaml files with helmCharts entries.
    Returns list of {name, repoUrl, files: []}
    """
    kustomization_files = list(root.rglob("kustomization.yaml"))

    # Process files concurrently
    tasks = [process_kustomization_file(yaml_file, root) for yaml_file in kustomization_files]
    results = await asyncio.gather(*tasks)

    # Merge results
    charts_map: dict[tuple[str, str], list[str]] = {}
    for file_charts in results:
        for (name, repo_url), file_path in file_charts:
            key = (name, repo_url)
            if key not in charts_map:
                charts_map[key] = []
            charts_map[key].append(file_path)

    # Convert to list format
    result = []
    for (name, repo_url), files in charts_map.items():
        result.append({"name": name, "repoUrl": repo_url, "files": sorted(files)})

    return sorted(result, key=lambda x: x["name"])


async def process_kustomization_file(yaml_file: Path, root: Path) -> list[tuple[tuple[str, str], str]]:
    """Process a single kustomization.yaml file."""
    data = await load_yaml_safe(yaml_file)
    if not data:
        return []

    helm_charts = data.get("helmCharts")
    if not isinstance(helm_charts, list):
        return []

    results = []
    for chart in helm_charts:
        name = chart.get("name")
        repo_url = chart.get("repo")

        if name and repo_url:
            results.append(((name, repo_url), str(yaml_file.relative_to(root))))

    return results


async def discover_chart_dependencies(root: Path) -> list[dict]:
    """
    Find all Chart.yaml files with dependencies.
    Returns list of {name, repoUrl, files: []}
    """
    chart_files = list(root.rglob("Chart.yaml"))

    # Process files concurrently
    tasks = [process_chart_file(yaml_file, root) for yaml_file in chart_files]
    results = await asyncio.gather(*tasks)

    # Merge results
    charts_map: dict[tuple[str, str], list[str]] = {}
    for file_deps in results:
        for (name, repo_url), file_path in file_deps:
            key = (name, repo_url)
            if key not in charts_map:
                charts_map[key] = []
            charts_map[key].append(file_path)

    # Convert to list format
    result = []
    for (name, repo_url), files in charts_map.items():
        result.append({"name": name, "repoUrl": repo_url, "files": sorted(files)})

    return sorted(result, key=lambda x: x["name"])


async def process_chart_file(yaml_file: Path, root: Path) -> list[tuple[tuple[str, str], str]]:
    """Process a single Chart.yaml file."""
    data = await load_yaml_safe(yaml_file)
    if not data:
        return []

    dependencies = data.get("dependencies")
    if not isinstance(dependencies, list):
        return []

    results = []
    for dep in dependencies:
        name = dep.get("name")
        repo_url = dep.get("repository")

        if name and repo_url:
            # Skip local dependencies (file:// or alias references)
            if not repo_url.startswith("http"):
                continue
            results.append(((name, repo_url), str(yaml_file.relative_to(root))))

    return results


def parse_image(image_str: str) -> tuple[str, str, str]:
    """
    Parse an image string into (registry, repository, tag).

    Examples:
        postgres:18.1 -> ("dockerhub", "library/postgres", "18.1")
        cloudflare/cloudflared:2025.11.1 -> ("dockerhub", "cloudflare/cloudflared", "2025.11.1")
        ghcr.io/owner/repo:v1.0 -> ("ghcr.io", "owner/repo", "v1.0")
        gcr.io/project/image:tag -> ("gcr.io", "project/image", "tag")
    """
    # Split off the tag. A real tag never contains "/" - if the text after
    # the last colon does, that colon is a registry:port separator (e.g.
    # "localhost:5000/myimage" with no tag at all), not a tag separator.
    if ":" in image_str:
        image_part, maybe_tag = image_str.rsplit(":", 1)
        if "/" in maybe_tag:
            image_part, tag = image_str, "latest"
        else:
            tag = maybe_tag
    else:
        image_part, tag = image_str, "latest"

    # Check if there's a registry prefix
    parts = image_part.split("/")

    # If first part has a dot or is localhost, it's a registry
    if len(parts) > 1 and ("." in parts[0] or ":" in parts[0] or parts[0] == "localhost"):
        registry = parts[0]
        repository = "/".join(parts[1:])
    else:
        # Docker Hub
        registry = "dockerhub"
        if len(parts) == 1:
            # Official image (library/)
            repository = f"library/{parts[0]}"
        else:
            repository = image_part

    return registry, repository, tag


def find_container_images_in_yaml(data: dict, current_path: list | None = None) -> list[tuple[list, str]]:
    """
    Recursively find all container image references in a Kubernetes manifest.
    Returns list of (yaml_path, image_string).
    """
    if current_path is None:
        current_path = []

    results = []

    if isinstance(data, dict):
        # Check if this is a container with an image
        if "image" in data and isinstance(data["image"], str):
            results.append((current_path + ["image"], data["image"]))

        # Check if this is initContainers or containers list
        for key in ["containers", "initContainers"]:
            if key in data and isinstance(data[key], list):
                for idx, container in enumerate(data[key]):
                    if isinstance(container, dict) and "image" in container:
                        results.append((current_path + [key, idx, "image"], container["image"]))

        # Recurse into other fields
        for key, value in data.items():
            if key not in ["image", "containers", "initContainers"]:
                results.extend(find_container_images_in_yaml(value, current_path + [key]))

    elif isinstance(data, list):
        for idx, item in enumerate(data):
            results.extend(find_container_images_in_yaml(item, current_path + [idx]))

    return results


async def discover_docker_images(root: Path) -> list[dict]:
    """
    Find all Docker images in Kubernetes manifests.
    Returns list of {id, registry, repository, file, yamlPath}
    """
    # Resource types that can have container images
    resource_types = {
        "Deployment",
        "StatefulSet",
        "DaemonSet",
        "Job",
        "CronJob",
        "Pod",
        "ReplicaSet",
        "ReplicationController",
    }

    # Find all YAML files
    yaml_files = []
    for yaml_file in root.rglob("*.yaml"):
        # Skip certain directories
        if any(part.startswith(".") for part in yaml_file.parts):
            continue
        yaml_files.append(yaml_file)

    # Process files concurrently
    tasks = [process_k8s_manifest_file(yaml_file, root, resource_types) for yaml_file in yaml_files]
    results = await asyncio.gather(*tasks)

    # Merge results
    images_map: dict[tuple[str, str], dict] = {}
    for file_images in results:
        for key, image_data in file_images:
            if key not in images_map:
                images_map[key] = image_data

    return sorted(images_map.values(), key=lambda x: x["id"])


async def process_k8s_manifest_file(
    yaml_file: Path, root: Path, resource_types: set
) -> list[tuple[tuple[str, str], dict]]:
    """Process a single Kubernetes manifest file."""
    data = await load_yaml_safe(yaml_file)
    if not data:
        return []

    # Check if it's a Kubernetes resource with containers
    if data.get("kind") not in resource_types:
        return []

    # Find all image references
    image_refs = find_container_images_in_yaml(data)

    results = []
    for yaml_path, image_str in image_refs:
        # Skip images without tags or with variables
        if ":" not in image_str or "$" in image_str or "{" in image_str:
            continue

        registry, repository, tag = parse_image(image_str)

        # Create a unique key
        key = (registry, repository)

        # Generate an ID from the repository name
        image_id = repository.split("/")[-1]

        image_data = {
            "id": image_id,
            "registry": registry,
            "repository": repository,
            "file": str(yaml_file.relative_to(root)),
            "yamlPath": yaml_path,
        }

        results.append((key, image_data))

    return results


async def generate_config(root: Path) -> dict:
    """Generate the full configuration using concurrent discovery."""
    print("Discovering resources...")

    # Run all discovery tasks concurrently
    argo_apps, kustomize_charts, chart_deps, docker_images = await asyncio.gather(
        discover_argo_apps(root),
        discover_kustomize_helm_charts(root),
        discover_chart_dependencies(root),
        discover_docker_images(root),
    )

    print(f"  Found {len(argo_apps)} Argo CD Applications with Helm charts")
    print(f"  Found {len(kustomize_charts)} unique Helm charts in kustomization files")
    print(f"  Found {len(chart_deps)} unique Helm charts in Chart.yaml dependencies")
    print(f"  Found {len(docker_images)} unique Docker images")

    config = {}

    if argo_apps:
        config["argoApps"] = argo_apps

    if kustomize_charts:
        config["kustomizeHelmCharts"] = kustomize_charts

    if chart_deps:
        config["chartDependencies"] = chart_deps

    if docker_images:
        config["dockerImages"] = docker_images

    return config


_SECTION_KEY_FNS = {
    "argoApps": lambda item: (item["name"], item["file"]),
    "kustomizeHelmCharts": lambda item: (item["name"], item["repoUrl"]),
    "chartDependencies": lambda item: (item["name"], item["repoUrl"]),
    "dockerImages": lambda item: (item["registry"], item["repository"]),
}


def _check_ignore(section: str, item: dict, ignore_config: dict | None) -> tuple[bool, str | None]:
    if section == "dockerImages":
        return should_ignore_docker_image(item, ignore_config)
    return should_ignore_helm_chart(item["name"], ignore_config)


def merge_configs(existing: dict, discovered: dict) -> dict:
    """
    Merge newly discovered resources into `existing` **in place**, appending
    only genuinely new entries to the end of each section's existing list.

    Existing entries, their order, and (when `existing` is a ruamel.yaml
    CommentedMap loaded in round-trip mode) any comments attached to them
    are never touched - only appended-to. This is what makes comment
    preservation possible without reimplementing a YAML comment model:
    nothing about the original structure is disturbed, and a brand-new
    list item has no comment to preserve in the first place. A match
    (by the same key discovery already used before this rewrite) means
    the existing entry wins untouched - discovery has only ever added
    entries, never updated an existing one's fields, so this preserves
    that behavior exactly.

    Any top-level key in `existing` this function doesn't know how to
    merge (an "ignore" section, or anything else - a section this
    script's schema doesn't cover, a stale/renamed section from before a
    schema change) is left alone automatically, since it's simply never
    touched, rather than needing to be explicitly copied over.

    Returns `existing` (now mutated).
    """
    ignore_config = existing.get("ignore")
    ignored_count = dict.fromkeys(_SECTION_KEY_FNS, 0)

    for section, key_fn in _SECTION_KEY_FNS.items():
        # Deliberately `is None`, not truthiness - an existing section that's
        # merely empty (`dockerImages: []`, possibly with its own trailing
        # comment) is a real node in the document and must not be replaced
        # wholesale just because len() == 0.
        existing_items = existing.get(section)
        if existing_items is None:
            existing_items = []
        discovered_items = discovered.get(section, [])
        existing_keys = {key_fn(item) for item in existing_items}

        new_items = []
        for item in discovered_items:
            if key_fn(item) in existing_keys:
                continue  # already tracked - existing entry (and its comments) wins, untouched
            ignored, reason = _check_ignore(section, item, ignore_config)
            label = item.get("name") or item.get("id")
            if ignored:
                ignored_count[section] += 1
                print(f"  [SKIP] {section} {label}: {reason}")
                continue
            new_items.append(item)
            print(f"  [NEW] {section}: {label}")

        if not new_items:
            continue
        if existing.get(section) is None:
            existing[section] = []
        existing[section].extend(new_items)

    total_ignored = sum(ignored_count.values())
    if total_ignored > 0:
        print(f"\nIgnored {total_ignored} resources based on ignore rules:")
        for section, count in ignored_count.items():
            if count > 0:
                print(f"  - {section}: {count}")

    return existing


async def async_main() -> int:
    """
    Async main function that discovers resources and generates config.

    Returns:
        Exit code (0 for success)
    """
    root = Path.cwd()
    # action.yml injects this from the config-path input - previously
    # ignored entirely, silently forcing every consumer onto
    # .update-config.yaml regardless of what they configured.
    config_path = root / os.environ.get("CONFIG_PATH", ".update-config.yaml")

    print("Auto-discovering resources in the repository...")

    discovered = await generate_config(root)

    # Load existing config if it exists
    if config_path.exists():
        print("Merging with existing configuration...")
        async with aiofiles.open(config_path, encoding="utf-8") as f:
            content = await f.read()
            existing = load_yaml_roundtrip(content) or CommentedMap()

        final_config = merge_configs(existing, discovered)
    else:
        print("Creating new configuration...")
        final_config = discovered

    # Write the config. Uses ruamel.yaml's round-trip mode, not plain
    # PyYAML - a plain yaml.safe_load/yaml.dump round-trip has no concept
    # of comments at all, so every comment in the existing file (including
    # ones documenting non-obvious schema quirks - the exact kind of thing
    # this script's own history has needed) would be silently stripped on
    # every auto-discover run. merge_configs() only ever appends new items
    # to existing lists in place rather than rebuilding the structure from
    # scratch, which is what makes this actually work end to end.
    if "--dry-run" in sys.argv:
        print(f"[DRY RUN] Would write configuration to {config_path}, skipping actual write.")
    else:
        print(f"Writing configuration to {config_path}...")
        async with aiofiles.open(config_path, "w", encoding="utf-8") as f:
            await f.write(dump_yaml_roundtrip(final_config))

    print("Configuration updated successfully!")
    print("Summary:")
    print(f"  - Argo CD Applications: {len(final_config.get('argoApps', []))}")
    print(f"  - Kustomize Helm Charts: {len(final_config.get('kustomizeHelmCharts', []))}")
    print(f"  - Chart.yaml Dependencies: {len(final_config.get('chartDependencies', []))}")
    print(f"  - Docker Images: {len(final_config.get('dockerImages', []))}")

    return 0


def main() -> int:
    """
    Entry point that runs the async main function.

    Returns:
        Exit code (0 for success)
    """
    return asyncio.run(async_main())


if __name__ == "__main__":
    sys.exit(main())
