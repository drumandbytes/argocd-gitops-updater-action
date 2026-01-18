#!/usr/bin/env python
"""
Auto-discover Helm charts and Docker images in the repository
and generate/update .update-config.yaml
"""
import sys
import re
from pathlib import Path
from typing import Any
import yaml


def load_yaml_safe(path: Path) -> dict | None:
    """Load YAML file, return None if it fails or isn't valid YAML."""
    try:
        with path.open("r", encoding="utf-8") as f:
            return yaml.safe_load(f)
    except Exception:
        return None


def should_ignore_docker_image(entry, ignore_config):
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


def should_ignore_helm_chart(name, ignore_config):
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


def discover_argo_apps(root: Path) -> list[dict[str, Any]]:
    """
    Find all Argo CD Application resources with Helm charts.
    Returns list of {name, repoUrl, file}
    """
    apps = []

    for yaml_file in root.rglob("*.yaml"):
        data = load_yaml_safe(yaml_file)
        if not data:
            continue

        # Check if it's an Argo CD Application
        if data.get("kind") != "Application":
            continue

        # Check if it uses a Helm chart
        try:
            source = data["spec"]["source"]
            chart = source.get("chart")
            repo_url = source.get("repoURL")

            if chart and repo_url:
                # Only include Helm chart repos (URLs starting with http/https)
                # Skip git repositories (ending with .git)
                if not repo_url.startswith("http"):
                    continue
                if repo_url.endswith(".git"):
                    continue

                apps.append({
                    "name": chart,
                    "repoUrl": repo_url,
                    "file": str(yaml_file.relative_to(root))
                })
        except (KeyError, TypeError):
            continue

    return sorted(apps, key=lambda x: x["name"])


def discover_kustomize_helm_charts(root: Path) -> list[dict[str, Any]]:
    """
    Find all kustomization.yaml files with helmCharts entries.
    Returns list of {name, repoUrl, files: []}
    """
    charts_map: dict[tuple[str, str], list[str]] = {}

    for yaml_file in root.rglob("kustomization.yaml"):
        data = load_yaml_safe(yaml_file)
        if not data:
            continue

        helm_charts = data.get("helmCharts")
        if not isinstance(helm_charts, list):
            continue

        for chart in helm_charts:
            name = chart.get("name")
            repo_url = chart.get("repo")

            if name and repo_url:
                key = (name, repo_url)
                if key not in charts_map:
                    charts_map[key] = []
                charts_map[key].append(str(yaml_file.relative_to(root)))

    # Convert to list format
    result = []
    for (name, repo_url), files in charts_map.items():
        result.append({
            "name": name,
            "repoUrl": repo_url,
            "files": sorted(files)
        })

    return sorted(result, key=lambda x: x["name"])


def discover_chart_dependencies(root: Path) -> list[dict[str, Any]]:
    """
    Find all Chart.yaml files with dependencies.
    Returns list of {name, repoUrl, files: []}
    """
    charts_map: dict[tuple[str, str], list[str]] = {}

    for yaml_file in root.rglob("Chart.yaml"):
        data = load_yaml_safe(yaml_file)
        if not data:
            continue

        dependencies = data.get("dependencies")
        if not isinstance(dependencies, list):
            continue

        for dep in dependencies:
            name = dep.get("name")
            repo_url = dep.get("repository")

            if name and repo_url:
                # Skip local dependencies (file:// or alias references)
                if not repo_url.startswith("http"):
                    continue

                key = (name, repo_url)
                if key not in charts_map:
                    charts_map[key] = []
                charts_map[key].append(str(yaml_file.relative_to(root)))

    # Convert to list format
    result = []
    for (name, repo_url), files in charts_map.items():
        result.append({
            "name": name,
            "repoUrl": repo_url,
            "files": sorted(files)
        })

    return sorted(result, key=lambda x: x["name"])


def parse_image(image_str: str) -> tuple[str, str, str]:
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


def find_container_images_in_yaml(data: dict, current_path: list = None) -> list[tuple[list, str]]:
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


def discover_docker_images(root: Path) -> list[dict[str, Any]]:
    """
    Find all Docker images in Kubernetes manifests.
    Returns list of {id, registry, repository, file, yamlPath}
    """
    # Resource types that can have container images
    resource_types = {
        "Deployment", "StatefulSet", "DaemonSet", "Job", "CronJob",
        "Pod", "ReplicaSet", "ReplicationController"
    }

    images_map: dict[tuple[str, str], dict] = {}

    for yaml_file in root.rglob("*.yaml"):
        # Skip certain directories
        if any(part.startswith(".") for part in yaml_file.parts):
            continue

        data = load_yaml_safe(yaml_file)
        if not data:
            continue

        # Check if it's a Kubernetes resource with containers
        if data.get("kind") not in resource_types:
            continue

        # Find all image references
        image_refs = find_container_images_in_yaml(data)

        for yaml_path, image_str in image_refs:
            # Skip images without tags or with variables
            if ":" not in image_str or "$" in image_str or "{" in image_str:
                continue

            registry, repository, tag = parse_image(image_str)

            # Create a unique key
            key = (registry, repository)

            # Use the first occurrence we find
            if key not in images_map:
                # Generate an ID from the repository name
                image_id = repository.split("/")[-1]

                images_map[key] = {
                    "id": image_id,
                    "registry": registry,
                    "repository": repository,
                    "file": str(yaml_file.relative_to(root)),
                    "yamlPath": yaml_path
                }

    return sorted(images_map.values(), key=lambda x: x["id"])


def generate_config(root: Path) -> dict:
    """Generate the full configuration."""
    print("Discovering Argo CD Applications...")
    argo_apps = discover_argo_apps(root)
    print(f"  Found {len(argo_apps)} Argo CD Applications with Helm charts")

    print("\nDiscovering Kustomize Helm charts...")
    kustomize_charts = discover_kustomize_helm_charts(root)
    print(f"  Found {len(kustomize_charts)} unique Helm charts in kustomization files")

    print("\nDiscovering Chart.yaml dependencies...")
    chart_deps = discover_chart_dependencies(root)
    print(f"  Found {len(chart_deps)} unique Helm charts in Chart.yaml dependencies")

    print("\nDiscovering Docker images...")
    docker_images = discover_docker_images(root)
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


def main():
    root = Path.cwd()
    config_path = root / ".update-config.yaml"

    print("Auto-discovering resources in the repository...\n")

    discovered = generate_config(root)

    # Load existing config if it exists
    if config_path.exists():
        print(f"\nMerging with existing configuration at {config_path}...")
        with config_path.open("r", encoding="utf-8") as f:
            existing = yaml.safe_load(f) or {}

        final_config = merge_configs(existing, discovered)
    else:
        print(f"\nNo existing configuration found, creating new one...")
        final_config = discovered

    # Write the config
    print(f"\nWriting configuration to {config_path}...")
    with config_path.open("w", encoding="utf-8") as f:
        yaml.dump(final_config, f, default_flow_style=False, sort_keys=False, allow_unicode=True)

    print("\n✅ Configuration updated successfully!")
    print(f"\nSummary:")
    print(f"  - Argo CD Applications: {len(final_config.get('argoApps', []))}")
    print(f"  - Kustomize Helm Charts: {len(final_config.get('kustomizeHelmCharts', []))}")
    print(f"  - Chart.yaml Dependencies: {len(final_config.get('chartDependencies', []))}")
    print(f"  - Docker Images: {len(final_config.get('dockerImages', []))}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
