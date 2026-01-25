#!/usr/bin/env python
"""
Auto-discover Helm charts and Docker images in the repository
and generate/update .update-config.yaml

This async version uses:
- asyncio for concurrent file operations
- aiofiles for non-blocking file I/O
- Concurrent processing for faster discovery
"""
import sys
import re
import asyncio
from pathlib import Path
from typing import Any, Optional, Tuple, List
import aiofiles
import yaml


async def load_yaml_safe(path: Path) -> Optional[dict]:
    """Load YAML file asynchronously, return None if it fails or isn't valid YAML."""
    try:
        async with aiofiles.open(path, "r", encoding="utf-8") as f:
            content = await f.read()
            return yaml.safe_load(content)
    except Exception:
        return None


def should_ignore_docker_image(entry: dict, ignore_config: Optional[dict]) -> Tuple[bool, Optional[str]]:
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


def should_ignore_helm_chart(name: str, ignore_config: Optional[dict]) -> Tuple[bool, Optional[str]]:
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


async def discover_argo_apps(root: Path) -> List[dict]:
    """
    Find all Argo CD Application resources with Helm charts.
    Returns list of {name, repoUrl, file}
    """
    yaml_files = list(root.rglob("*.yaml"))

    # Process files concurrently
    tasks = [process_argo_app_file(yaml_file, root) for yaml_file in yaml_files]
    results = await asyncio.gather(*tasks)

    # Filter out None results and sort
    apps = [app for app in results if app is not None]
    return sorted(apps, key=lambda x: x["name"])


async def process_argo_app_file(yaml_file: Path, root: Path) -> Optional[dict]:
    """Process a single YAML file to check if it's an Argo CD Application."""
    data = await load_yaml_safe(yaml_file)
    if not data:
        return None

    # Check if it's an Argo CD Application
    if data.get("kind") != "Application":
        return None

    # Check if it uses a Helm chart
    try:
        source = data["spec"]["source"]
        chart = source.get("chart")
        repo_url = source.get("repoURL")

        if chart and repo_url:
            # Only include Helm chart repos (URLs starting with http/https)
            # Skip git repositories (ending with .git)
            if not repo_url.startswith("http"):
                return None
            if repo_url.endswith(".git"):
                return None

            return {
                "name": chart,
                "repoUrl": repo_url,
                "file": str(yaml_file.relative_to(root))
            }
    except (KeyError, TypeError):
        return None

    return None


async def discover_kustomize_helm_charts(root: Path) -> List[dict]:
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
        result.append({
            "name": name,
            "repoUrl": repo_url,
            "files": sorted(files)
        })

    return sorted(result, key=lambda x: x["name"])


async def process_kustomization_file(yaml_file: Path, root: Path) -> List[Tuple[Tuple[str, str], str]]:
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


async def discover_chart_dependencies(root: Path) -> List[dict]:
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
        result.append({
            "name": name,
            "repoUrl": repo_url,
            "files": sorted(files)
        })

    return sorted(result, key=lambda x: x["name"])


async def process_chart_file(yaml_file: Path, root: Path) -> List[Tuple[Tuple[str, str], str]]:
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


def parse_image(image_str: str) -> Tuple[str, str, str]:
    """
    Parse an image string into (registry, repository, tag).

    Examples:
        postgres:18.1 -> ("dockerhub", "library/postgres", "18.1")
        cloudflare/cloudflared:2025.11.1 -> ("dockerhub", "cloudflare/cloudflared", "2025.11.1")
        ghcr.io/owner/repo:v1.0 -> ("ghcr.io", "owner/repo", "v1.0")
        gcr.io/project/image:tag -> ("gcr.io", "project/image", "tag")
    """
    # Split off the tag
    if ":" in image_str:
        image_part, tag = image_str.rsplit(":", 1)
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


def find_container_images_in_yaml(data: dict, current_path: Optional[list] = None) -> List[Tuple[list, str]]:
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
                        results.append(
                            (current_path + [key, idx, "image"], container["image"])
                        )

        # Recurse into other fields
        for key, value in data.items():
            if key not in ["image", "containers", "initContainers"]:
                results.extend(find_container_images_in_yaml(value, current_path + [key]))

    elif isinstance(data, list):
        for idx, item in enumerate(data):
            results.extend(find_container_images_in_yaml(item, current_path + [idx]))

    return results


async def discover_docker_images(root: Path) -> List[dict]:
    """
    Find all Docker images in Kubernetes manifests.
    Returns list of {id, registry, repository, file, yamlPath}
    """
    # Resource types that can have container images
    resource_types = {
        "Deployment", "StatefulSet", "DaemonSet", "Job", "CronJob",
        "Pod", "ReplicaSet", "ReplicationController"
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


async def process_k8s_manifest_file(yaml_file: Path, root: Path, resource_types: set) -> List[Tuple[Tuple[str, str], dict]]:
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
            "yamlPath": yaml_path
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
        discover_docker_images(root)
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


def merge_configs(existing: dict, discovered: dict) -> dict:
    """
    Merge discovered config with existing config.
    Preserves any manual customizations in the existing config.
    Also preserves and applies ignore rules.
    """
    merged = {}

    # Preserve ignore section from existing config
    ignore_config = existing.get("ignore")
    if ignore_config:
        merged["ignore"] = ignore_config

    ignored_count = {"argoApps": 0, "kustomizeHelmCharts": 0, "chartDependencies": 0, "dockerImages": 0}

    # For each section, we'll use discovered as base but preserve manual entries
    for section in ["argoApps", "kustomizeHelmCharts", "chartDependencies", "dockerImages"]:
        existing_items = existing.get(section, [])
        discovered_items = discovered.get(section, [])

        if section == "argoApps":
            # Filter discovered items based on ignore rules
            filtered_discovered = []
            for item in discovered_items:
                ignored, reason = should_ignore_helm_chart(item["name"], ignore_config)
                if ignored:
                    ignored_count[section] += 1
                    print(f"  [SKIP] Argo App {item['name']}: {reason}")
                else:
                    filtered_discovered.append(item)

            # Key by (name, file)
            existing_map = {(item["name"], item["file"]): item for item in existing_items}
            discovered_map = {(item["name"], item["file"]): item for item in filtered_discovered}

            # Merge
            merged_map = {**discovered_map, **existing_map}
            merged[section] = sorted(merged_map.values(), key=lambda x: (x["name"], x["repoUrl"], x["file"]))

        elif section == "kustomizeHelmCharts":
            # Filter discovered items based on ignore rules
            filtered_discovered = []
            for item in discovered_items:
                ignored, reason = should_ignore_helm_chart(item["name"], ignore_config)
                if ignored:
                    ignored_count[section] += 1
                    print(f"  [SKIP] Kustomize Helm Chart {item['name']}: {reason}")
                else:
                    filtered_discovered.append(item)

            # Key by (name, repoUrl)
            existing_map = {(item["name"], item["repoUrl"]): item for item in existing_items}
            discovered_map = {(item["name"], item["repoUrl"]): item for item in filtered_discovered}

            # Merge
            merged_map = {**discovered_map, **existing_map}
            merged[section] = sorted(merged_map.values(), key=lambda x: (x["name"], x.get("repoUrl", "")))

        elif section == "chartDependencies":
            # Filter discovered items based on ignore rules
            filtered_discovered = []
            for item in discovered_items:
                ignored, reason = should_ignore_helm_chart(item["name"], ignore_config)
                if ignored:
                    ignored_count[section] += 1
                    print(f"  [SKIP] Chart.yaml dependency {item['name']}: {reason}")
                else:
                    filtered_discovered.append(item)

            # Key by (name, repoUrl)
            existing_map = {(item["name"], item["repoUrl"]): item for item in existing_items}
            discovered_map = {(item["name"], item["repoUrl"]): item for item in filtered_discovered}

            # Merge
            merged_map = {**discovered_map, **existing_map}
            merged[section] = sorted(merged_map.values(), key=lambda x: (x["name"], x.get("repoUrl", "")))

        elif section == "dockerImages":
            # Filter discovered items based on ignore rules
            filtered_discovered = []
            for item in discovered_items:
                ignored, reason = should_ignore_docker_image(item, ignore_config)
                if ignored:
                    ignored_count[section] += 1
                    print(f"  [SKIP] Docker Image {item['id']}: {reason}")
                else:
                    filtered_discovered.append(item)

            # Key by (registry, repository)
            existing_map = {(item["registry"], item["repository"]): item for item in existing_items}
            discovered_map = {(item["registry"], item["repository"]): item for item in filtered_discovered}

            # Merge
            merged_map = {**discovered_map, **existing_map}
            merged[section] = sorted(merged_map.values(), key=lambda x: (x["id"], x["registry"], x["repository"]))

    # Print summary of ignored items
    total_ignored = sum(ignored_count.values())
    if total_ignored > 0:
        print(f"\nIgnored {total_ignored} resources based on ignore rules:")
        for section, count in ignored_count.items():
            if count > 0:
                print(f"  - {section}: {count}")

    return merged


async def async_main():
    """Async main function."""
    root = Path.cwd()
    config_path = root / ".update-config.yaml"

    print("Auto-discovering resources in the repository...")

    discovered = await generate_config(root)

    # Load existing config if it exists
    if config_path.exists():
        print(f"Merging with existing configuration...")
        async with aiofiles.open(config_path, "r", encoding="utf-8") as f:
            content = await f.read()
            existing = yaml.safe_load(content) or {}

        final_config = merge_configs(existing, discovered)
    else:
        print(f"Creating new configuration...")
        final_config = discovered

    # Write the config
    print(f"Writing configuration to {config_path}...")
    async with aiofiles.open(config_path, "w", encoding="utf-8") as f:
        await f.write(yaml.dump(final_config, default_flow_style=False, sort_keys=False, allow_unicode=True))

    print(f"Configuration updated successfully!")
    print(f"Summary:")
    print(f"  - Argo CD Applications: {len(final_config.get('argoApps', []))}")
    print(f"  - Kustomize Helm Charts: {len(final_config.get('kustomizeHelmCharts', []))}")
    print(f"  - Chart.yaml Dependencies: {len(final_config.get('chartDependencies', []))}")
    print(f"  - Docker Images: {len(final_config.get('dockerImages', []))}")

    return 0


def main():
    """Entry point that runs the async main function."""
    return asyncio.run(async_main())


if __name__ == "__main__":
    sys.exit(main())
