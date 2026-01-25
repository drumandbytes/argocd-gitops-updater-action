# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

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
