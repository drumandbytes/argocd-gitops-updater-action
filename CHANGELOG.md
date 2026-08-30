# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Fixed
- Both `create-pull-request` steps (auto-discovery PR and version-update PR) now actually use the `github-token` input, instead of silently ignoring it and hardcoding `${{ github.token }}`. Previously, a caller passing a custom `github-token` (e.g. a GitHub App installation token) got it applied only to registry auth inside the Python scripts - the PR itself was still always authored as `github-actions[bot]` using the job's own default token, regardless of what was passed in.

## [2.2.0] - 2026-08-30

### Changed
- `discover-resources.py` now uses `ruamel.yaml`'s round-trip mode to read/write `.update-config.yaml`, instead of plain PyYAML. Every existing comment in the file is now preserved across an auto-discover run - previously, every single comment was silently stripped on every run, since plain `yaml.safe_load`/`yaml.dump` has no concept of comments at all.
- `merge_configs` now appends genuinely new entries to the end of each section's existing list in place, rather than rebuilding and re-sorting the whole list from scratch. Behaviorally identical to before (an existing entry always won over a matching discovered one; that's unchanged), but this is also what makes comment preservation possible - nothing about the original structure is disturbed except appending brand-new items, which have no comment to preserve in the first place.

## [2.1.4] - 2026-08-30

### Fixed
- Discovery and version-checking for Argo CD Applications now also check the multi-source shape (`spec.sources[]`), not just the legacy single-source shape (`spec.source`). Every multi-source Helm-chart Application was previously invisible to both `discover-resources.py` and `update-versions.py` - confirmed against a real consuming repo where this meant zero Helm charts were ever discovered or updated.
- `discover-resources.py`'s config merge no longer silently drops top-level sections it doesn't recognize (e.g. a `helmCharts` section pre-dating the `argoApps`/`kustomizeHelmCharts`/`chartDependencies` split). They're now preserved as-is with a log line, instead of being deleted from `.update-config.yaml` on the next auto-discover run.
- Replaced the deprecated `aiohttp.BasicAuth` + `auth=` kwarg (removed in aiohttp 4.0) with `aiohttp.encode_basic_auth()` + `headers=`, per aiohttp's own deprecation guidance, in both the Docker Hub and GHCR token-exchange requests.

## [2.1.0]

### Added
- Automated release workflow with label-based version bumping (release:major/minor/patch)
- Changelog extraction from [Unreleased] section for release notes
- Floating major version tag management (v1, v2, etc.)
- CI workflow for linting (ruff) and testing (pytest)
- Unit tests for version parsing, ignore rules, YAML replacement, discovery (64 tests)
- Edge case tests for graceful error handling (47 tests)
- CONTRIBUTING.md with development guidelines
- GitHub issue and PR templates
- ruff.toml configuration for code quality
- This CHANGELOG file

### Changed
- Modernized type annotations (tuple instead of Tuple, X | None instead of Optional)
- Complete type hint coverage for all functions
- Improved code organization with import sorting

### Fixed
- Invalid regex patterns in ignore rules now warn and skip instead of crashing
- Fixed inaccurate comments (multi-registry support, GITHUB_TOKEN encoding, docstring params)

## [2.0.0] - 2025-01-25

### BREAKING CHANGES
- Removed `cache` input parameter - caching system removed as async provides sufficient performance
- If you were using `cache: true`, simply remove this line from your workflow

### Added
- Async/await refactoring for concurrent API requests
- Pre-compiled regex patterns for better performance
- O(1) ignore rule lookups
- Improved error messages showing exception types

### Fixed
- Fixed versionPattern filtering for Docker images
- Fixed variant matching (no-variant vs with-variant)
- Fixed major version showing in reports when filtered by versionPattern

### Changed
- ~40-60s typical runtime for 10-15 resources
- Reduced Helm concurrency (10→5) for better stability
- Smart per-registry rate limiting
- Upgraded to Python 3.14
- Dependencies: aiohttp, aiofiles, pyyaml, packaging
- Removed: aiohttp-client-cache, aiosqlite

### Documentation
- Updated all docs to reflect async-only implementation
- Removed outdated cache documentation
- Realistic performance expectations

## [1.3.0] - 2025-01-25

### Changed
- Refactored to async/await architecture for 3-4x performance improvement
- Removed cache system in favor of direct API calls (caching conflicts with need for fresh data)
- Pre-compile regex patterns for O(1) ignore rule lookups

### Fixed
- Improved error logging with full tracebacks
- Reduced Helm concurrency to prevent timeout issues
- Fixed versionPattern filtering for Docker images
- Enforced exact variant matching (alpine stays alpine, no-variant stays no-variant)

## [1.2.0] - 2025-01-24

### Added
- Support for `versionPattern` in ignore rules for fine-grained filtering
- Major version upgrade notifications (warns but doesn't auto-update)
- Variant preservation for Docker images (alpine, debian, slim tags)
- Per-registry rate limiting with configurable concurrency

### Changed
- Upgraded to Python 3.14 for latest performance improvements
- Sequential Helm/Docker processing for reliability (parallel caused timeouts)

## [1.1.0] - 2025-01-23

### Added
- Auto-discovery feature for Helm charts and Docker images
- Support for Argo CD Applications with Helm sources
- Support for Kustomize helmCharts entries
- Support for Chart.yaml dependencies
- Docker image discovery in Kubernetes manifests

### Changed
- Improved notification formatting for Slack, Discord, Teams, and Telegram

## [1.0.0] - 2025-01-22

### Added
- Initial release
- Helm chart version updates from repository index
- Docker image tag updates from multiple registries:
  - Docker Hub (with optional authentication)
  - GitHub Container Registry (ghcr.io)
  - Quay.io
  - Google Container Registry (gcr.io)
- Semantic version comparison
- Ignore rules for skipping specific images/charts
- Pull request creation with update summary
- Notification support:
  - Telegram
  - Slack
  - Discord
  - Microsoft Teams
- Dry-run mode for testing
