# Container & Helm Version Updater

Automatically update Helm chart versions and Docker image tags in your GitOps repository.

## Features

✅ **Automatic Discovery** - Scan your repository and auto-generate configuration
✅ **Image Variant Preservation** - Keeps alpine images on alpine, debian on debian
✅ **Multi-Registry Support** - Works with Docker Hub, ghcr.io, quay.io, gcr.io, and more
✅ **Semantic Versioning** - Only updates within the same major version
✅ **Major Version Detection** - Notifies when newer major versions are available
✅ **Ignore/Blacklist** - Exclude specific images or charts from updates
✅ **High Performance** - Concurrent processing + caching for 5-10x speed improvement
✅ **GitOps-Friendly** - Creates PRs for review before merging
✅ **Configurable** - Full control over what gets updated and how

## Quick Start

### 1. Auto-discover Resources

Run the discovery script to automatically generate your configuration:

```bash
uv run python .github/scripts/discover-resources.py
```

This will create/update `.update-config.yaml` with all discovered:
- Argo CD Applications using Helm charts
- Kustomize Helm chart references
- Docker images in Kubernetes manifests

### 2. Review Configuration

Check the generated `.update-config.yaml`:

```yaml
argoApps:
  - name: argo-cd
    repoUrl: https://argoproj.github.io/argo-helm
    file: bootstrap/argo-cd/argo-cd.yaml

kustomizeHelmCharts:
  - name: kube-prometheus-stack
    repoUrl: https://prometheus-community.github.io/helm-charts
    files:
      - apps/monitoring/prometheus/kustomization.yaml

dockerImages:
  - id: postgres
    registry: dockerhub
    repository: library/postgres
    file: apps/postgres/base/statefulset.yaml
    yamlPath: ["spec", "template", "spec", "containers", 0, "image"]
```

### 3. Run Updates

Test with dry-run first:

```bash
uv run python .github/scripts/update-versions.py --dry-run
```

Then run for real:

```bash
uv run python .github/scripts/update-versions.py
```

## Configuration

### Docker Images

The `dockerImages` section tracks container images across registries:

```yaml
dockerImages:
  - id: postgres                    # Unique identifier
    registry: dockerhub              # Registry type
    repository: library/postgres     # Repository path
    file: apps/postgres/base/statefulset.yaml
    yamlPath: ["spec", "template", "spec", "containers", 0, "image"]
```

#### Supported Registries

| Registry | Value | Authentication | Rate Limit (Anon → Auth) | Status |
|----------|-------|----------------|--------------------------|--------|
| Docker Hub | `dockerhub` | Optional (recommended) | 100 → 200 req/6h | ✅ Tested & Working |
| Quay.io | `quay.io` | Not required | ~100 req/min | ✅ Tested & Working |
| Google Container Registry | `gcr.io` | Not required | No strict limit | ✅ Tested & Working |
| GitHub Container Registry | `ghcr.io` | **Required** | 5,000 req/h | ⚠️ Requires `GITHUB_TOKEN` |
| Generic Registry | `registry.example.com` | Varies | Varies | 🔧 Untested |

##### Docker Hub Authentication (Recommended)

Authenticating with Docker Hub **doubles the rate limit** and increases concurrent processing:

**Without auth:**
- 100 requests per 6 hours
- 3 concurrent requests

**With auth (free account):**
- 200 requests per 6 hours
- 5 concurrent requests
- 🚀 ~40% faster for Docker Hub images

**Setup:**
1. Get Docker Hub Access Token:
   - Go to https://hub.docker.com/settings/security
   - Click "New Access Token"
   - Give it a name (e.g., "version-updater")
   - Copy the token

2. Add to GitHub Secrets:
   - Go to repository **Settings** → **Secrets and variables** → **Actions**
   - Add secrets:
     - `DOCKERHUB_USERNAME`: Your Docker Hub username
     - `DOCKERHUB_TOKEN`: The access token you created

3. That's it! The workflow automatically uses these credentials.

**Local testing:**
```bash
export DOCKERHUB_USERNAME="your-username"
export DOCKERHUB_TOKEN="your-token"
uv run python .github/scripts/update-versions.py
```

**Note on ghcr.io**: GitHub Container Registry requires authentication even for public packages. The `GITHUB_TOKEN` is automatically available in GitHub Actions workflows, so ghcr.io images will work in automated runs but may fail in local testing without a token.

#### Image Variant Preservation

The updater automatically detects and preserves image variants:

- **Alpine** - `postgres:18.1-alpine3.22` → `postgres:18.2-alpine3.23`
- **Debian** - `node:20.10-debian` → `node:20.11-debian`
- **Slim** - `python:3.11-slim` → `python:3.12-slim`

Variants are detected by analyzing the tag suffix. If your current image uses alpine, only alpine tags will be considered for updates.

### Helm Charts

#### Argo CD Applications

Tracks Helm charts deployed via Argo CD:

```yaml
argoApps:
  - name: argo-cd
    repoUrl: https://argoproj.github.io/argo-helm
    file: bootstrap/argo-cd/argo-cd.yaml
```

Updates the `spec.source.targetRevision` field.

#### Kustomize Helm Charts

Tracks Helm charts referenced in `kustomization.yaml`:

```yaml
kustomizeHelmCharts:
  - name: kube-prometheus-stack
    repoUrl: https://prometheus-community.github.io/helm-charts
    files:
      - apps/monitoring/prometheus/kustomization.yaml
```

Updates the `helmCharts[].version` field.

## Ignoring Resources (Blacklist)

You can exclude specific Docker images or Helm charts from automatic updates and discovery using the `ignore` section in `.update-config.yaml`.

### Configuration

Add an `ignore` section to your config file:

```yaml
ignore:
  dockerImages:
    - id: "postgres"                          # Ignore by exact ID
    - repository: "library/mysql"             # Ignore by repository
    - repository: "library/postgres"          # Ignore specific tags using regex
      tagPattern: "17\\..*"                   # Ignore postgres 17.x versions

  helmCharts:
    - name: "kube-prometheus-stack"           # Ignore entire chart
    - name: "argo-cd"                         # Ignore specific versions using regex
      versionPattern: "7\\..*"                # Ignore argo-cd 7.x versions
```

### Docker Image Ignore Rules

**Ignore by ID** - Exclude a specific image entry by its unique ID:
```yaml
ignore:
  dockerImages:
    - id: "postgres"
```

**Ignore by Repository** - Exclude all images from a repository:
```yaml
ignore:
  dockerImages:
    - repository: "library/redis"
    - repository: "dbeaver/cloudbeaver"
```

**Ignore by Tag Pattern** - Exclude specific versions using regex:
```yaml
ignore:
  dockerImages:
    - repository: "library/postgres"
      tagPattern: "17\\..*"              # Ignore all postgres 17.x tags
    - repository: "library/node"
      tagPattern: ".*-bullseye"          # Ignore all bullseye variants
```

### Helm Chart Ignore Rules

**Ignore by Name** - Exclude an entire Helm chart:
```yaml
ignore:
  helmCharts:
    - name: "cert-manager"
```

**Ignore by Version Pattern** - Exclude specific versions:
```yaml
ignore:
  helmCharts:
    - name: "argo-cd"
      versionPattern: "7\\..*"           # Ignore version 7.x
    - name: "nginx-ingress"
      versionPattern: ".*-rc.*"          # Ignore release candidates
```

### Pattern Syntax

The `tagPattern` and `versionPattern` fields use Python regular expressions:

- `17\\..*` - Matches "17.0", "17.1.2", etc. (major version 17)
- `.*-alpine.*` - Matches any tag containing "-alpine"
- `^latest$` - Matches exactly "latest"
- `.*-rc.*` - Matches release candidates like "1.2.3-rc1"

**Note**: Remember to escape dots with `\\.` in regex patterns.

### Behavior

- **Auto-Discovery**: Ignored resources won't be added during auto-discovery
- **Updates**: Ignored resources are skipped during version updates
- **Reporting**: Skipped items are logged with `[SKIP]` messages
- **Preservation**: The ignore section is preserved when running auto-discovery

### Example Use Cases

**Prevent major version upgrades:**
```yaml
ignore:
  dockerImages:
    - repository: "library/postgres"
      tagPattern: "17\\..*"              # Stay on postgres 16.x
```

**Avoid unstable releases:**
```yaml
ignore:
  helmCharts:
    - name: "cert-manager"
      versionPattern: ".*-alpha.*"       # Skip alpha releases
    - name: "argo-cd"
      versionPattern: ".*-rc.*"          # Skip release candidates
```

**Exclude third-party images:**
```yaml
ignore:
  dockerImages:
    - repository: "thirdparty/legacy-app"  # Don't update legacy app
```

**Temporarily freeze a component:**
```yaml
ignore:
  helmCharts:
    - name: "kube-prometheus-stack"    # Freeze during migration
```

## Performance Optimizations

The updater includes several performance optimizations for fast execution:

### Concurrent Processing

Docker images and Helm charts are processed in parallel using thread pools:

```
Traditional Sequential:
  Image 1 (2s) → Image 2 (2s) → Image 3 (2s) = 6s total

Concurrent Processing:
  Image 1 (2s) ┐
  Image 2 (2s) ├─→ All complete in ~2-3s
  Image 3 (2s) ┘
```

**Configuration**: Up to 10 workers process resources simultaneously, significantly reducing total processing time (actual speedup depends on registry rate limits and network conditions).

### Registry Rate Limiting

Each registry has different API rate limits. The updater implements **per-registry concurrency limits** to prevent hitting rate limits:

| Registry | Concurrent Requests | Rate Limit (API) | Our Limit Reason |
|----------|-------------------|------------------|------------------|
| **Docker Hub** | 3 (anonymous)<br>5 (authenticated) | 100 req/6h (anonymous)<br>200 req/6h (authenticated) | Most restrictive |
| **ghcr.io** | 10 | 5,000 req/h (with token) | Very generous |
| **quay.io** | 5 | ~100 req/min | Moderate |
| **gcr.io** | 5 | No strict limit | Lenient |

**Tip:** Set `DOCKERHUB_USERNAME` and `DOCKERHUB_TOKEN` environment variables (or GitHub Secrets) to automatically increase Docker Hub's concurrent limit from 3 to 5.

**How it works:**
```python
# Even with 50 Docker Hub images, only 3 are checked at once
Docker Hub: [Image 1, Image 2, Image 3] ← Active (semaphore: 3/3)
Docker Hub: [Image 4, Image 5, ...Image 50] ← Waiting

# But ghcr.io can process 10 at once
ghcr.io: [Image 1...Image 10] ← Active (semaphore: 10/10)
```

**Benefits:**
- ✅ Prevents 429 "Rate Limit Exceeded" errors
- ✅ Automatically throttles per registry
- ✅ Other registries not affected by slow registries
- ✅ Safe for repositories with 100+ images

**Retry logic:**
If rate limited (429 error), the script automatically retries with exponential backoff:
- Attempt 1: Immediate
- Attempt 2: Wait 2 seconds
- Attempt 3: Wait 4 seconds
- Attempt 4: Wait 8 seconds
- Then fail with error

### HTTP Request Caching

Registry API responses are cached for 6 hours using SQLite:

- **First run (no cache)**: ~20-30s for 10 images (mostly HTTP request time)
- **Fully cached run**: ~2-5s for 10 images (5-10x faster, within 6-hour cache window)
- **Partially cached run**: ~8-15s for 10 images (2-3x faster, some cache expired)
- **Cache location**: `.registry_cache/` directory (automatically created)

**Benefits**:
- 5-10x speedup for repeated runs (when cache is fresh)
- Reduces API rate limiting issues
- Works offline after first run (with stale cache fallback)

### Performance Summary Example

```
============================================================
Performance Summary:
  Helm charts: 2.34s (8 charts)
  Docker images: 1.87s (10 images)
  Total time: 4.21s
============================================================
```

**Typical Performance** (for 10 Docker images + 8 Helm charts):
- First run (no cache): 15-25 seconds
- Subsequent runs (cached): 2-5 seconds
- **Improvement**: 3-12x faster (typically ~5x, depending on cache hit rate)

### Cache Management

The cache is automatically managed:
- **Expiration**: 6 hours (configurable in code)
- **Storage**: `.registry_cache/http_cache.sqlite`
- **Size**: Typically <10MB
- **Cleanup**: Delete `.registry_cache/` to clear

**To disable caching**: Replace `CACHE_SESSION` with `requests` in the code (not recommended).

### Thread Safety

All file operations use locks to prevent race conditions:
- Multiple threads can read registry APIs simultaneously
- File writes are serialized to prevent corruption
- Safe for concurrent execution

## GitHub Actions Integration

### Manual Workflow Triggers

The workflow supports manual triggers with options:

1. Go to **Actions** → **Update Helm charts and Docker images**
2. Click **Run workflow**
3. Choose options:
   - **auto-discover**: Automatically discover resources before updating
   - **dry-run**: Preview changes without creating a PR

#### Auto-Discovery Behavior

When `auto-discover` is enabled:

1. **Discovery Phase**: Scans repository for new resources
2. **Change Detection**: Checks if `.update-config.yaml` was modified
3. **Separate PR**: If changes found, creates a PR with title "chore: auto-discover new Helm charts & Docker images"
4. **Workflow Stops**: Exits successfully after creating discovery PR
5. **Manual Review**: You review and merge the discovery PR
6. **Next Run**: Subsequent runs will include the newly discovered resources in version updates

This ensures new resources are reviewed before they start receiving automatic version updates.

### Scheduled Updates

The workflow runs automatically daily at 5:00 AM UTC via cron schedule.

### Workflow Configuration

```yaml
name: Update Helm charts and Docker images

on:
  schedule:
    - cron: "0 5 * * *"
  workflow_dispatch:
    inputs:
      auto-discover:
        description: 'Auto-discover resources before updating'
        type: choice
        options: ['true', 'false']
      dry-run:
        description: 'Run in dry-run mode without making changes'
        type: choice
        options: ['true', 'false']
```

## Update Strategy

### Docker Images

**Same Major Version Only**
Images are only updated within the same major version:
- ✅ `postgres:18.1` → `postgres:18.2`
- ❌ `postgres:18.1` → `postgres:19.0`

When a new major version is available, you'll see a warning:
```
[INFO] New major available in library/postgres: 19.0
       (current major 18, new major 19)
```

**Tag Filtering**
The updater filters out pre-release tags:
- ❌ `alpha`, `beta`, `rc` tags are excluded
- ✅ `X.Y.Z-b` tags are allowed (used by some images)

### Helm Charts

Always updates to the latest available version in the chart repository.

## Examples

### Example 1: Alpine Image Preservation

**Before:**
```yaml
image: postgres:18.1-alpine3.22
```

**After:**
```yaml
image: postgres:18.2-alpine3.23
```

Notice both the version (18.1 → 18.2) and alpine version (3.22 → 3.23) were updated while preserving the alpine variant.

### Example 2: Multi-Registry Setup

```yaml
dockerImages:
  # Docker Hub official image
  - id: nginx
    registry: dockerhub
    repository: library/nginx
    file: apps/nginx/deployment.yaml
    yamlPath: ["spec", "template", "spec", "containers", 0, "image"]

  # Quay.io (public image, no auth needed)
  - id: prometheus
    registry: quay.io
    repository: prometheus/node-exporter
    file: apps/monitoring/deployment.yaml
    yamlPath: ["spec", "template", "spec", "containers", 0, "image"]

  # Google Container Registry (public image, no auth needed)
  - id: distroless
    registry: gcr.io
    repository: distroless/static
    file: apps/minimal/deployment.yaml
    yamlPath: ["spec", "template", "spec", "containers", 0, "image"]

  # GitHub Container Registry (requires GITHUB_TOKEN)
  - id: custom-app
    registry: ghcr.io
    repository: myorg/custom-app
    file: apps/custom-app/deployment.yaml
    yamlPath: ["spec", "template", "spec", "containers", 0, "image"]
```

**Note**: The ghcr.io example will only work in GitHub Actions (where `GITHUB_TOKEN` is automatically available) or when `GITHUB_TOKEN` is set in your environment.

### Example 3: Multiple Files

Track the same Helm chart across multiple overlays:

```yaml
kustomizeHelmCharts:
  - name: prometheus-postgres-exporter
    repoUrl: https://prometheus-community.github.io/helm-charts
    files:
      - apps/monitoring/postgres-exporter/overlays/dev/kustomization.yaml
      - apps/monitoring/postgres-exporter/overlays/prod/kustomization.yaml
      - apps/monitoring/postgres-exporter/overlays/staging/kustomization.yaml
```

All files will be updated to the same version.

## Scripts

### discover-resources.py

Auto-discovers resources in your repository.

**Usage:**
```bash
uv run python .github/scripts/discover-resources.py
```

**What it finds:**
- Argo CD Application resources with Helm charts
- kustomization.yaml files with helmCharts entries
- Deployment/StatefulSet/DaemonSet with container images

**Merge behavior:**
- Preserves manually added entries
- Updates with newly discovered resources
- Removes nothing (conservative approach)

### update-versions.py

Updates resources to their latest versions.

**Usage:**
```bash
# Dry-run (preview changes)
uv run python .github/scripts/update-versions.py --dry-run

# Real run (makes changes)
uv run python .github/scripts/update-versions.py
```

**Output:**
- Prints detailed update information
- Creates `.update-report.txt` with summary
- Makes surgical changes (preserves formatting and comments)

## Notifications

### Telegram Integration

The workflow can send notifications to Telegram:

1. Create a Telegram bot via [@BotFather](https://t.me/botfather)
2. Get your chat ID
3. Add secrets to your repository:
   - `TELEGRAM_BOT_TOKEN`
   - `TELEGRAM_CHAT_ID`

Notifications include:
- PR URL
- Operation type (created/updated)
- Update summary

## Troubleshooting

### Image not being updated

**Check variant matching:**
If you have `nginx:1.25-alpine` but it's not updating, verify that alpine tags exist for newer versions. The updater will only consider tags with the same variant.

**Check major version:**
The updater only updates within the same major version. If `2.0.0` is available but you're on `1.9.0`, it won't auto-update (by design).

### Authentication errors

**GitHub Container Registry (ghcr.io):**
```
[WARN] ghcr.io requires authentication. Set GITHUB_TOKEN environment variable.
```

ghcr.io requires authentication even for public packages. Solutions:
1. **In GitHub Actions**: Token is automatically available (no action needed)
2. **Local testing**: Set environment variable:
   ```bash
   export GITHUB_TOKEN="ghp_your_token_here"
   uv run python .github/scripts/update-versions.py
   ```
3. **Create a token**: Go to GitHub Settings → Developer settings → Personal access tokens → Generate new token (classic) with `read:packages` scope

**Other private registries:**
For private registries requiring authentication, you may need to:
1. Add registry credentials as repository secrets
2. Modify the scripts to include authentication headers
3. Or use GitHub Actions with pre-configured registry access

### Auto-discovery missing resources

**Excluded paths:**
Auto-discovery skips:
- Hidden directories (starting with `.`)
- Files without valid YAML
- Images with variables (`${IMAGE_TAG}`)

**Manual addition:**
You can always manually add entries to `.update-config.yaml` that auto-discovery might miss.

## Best Practices

### 1. Run Auto-Discovery Regularly

Add it to your workflow:
```yaml
- name: Auto-discover new resources
  run: uv run python .github/scripts/discover-resources.py
```

### 2. Review PRs Carefully

Always review the generated PRs before merging:
- Check for breaking changes in release notes
- Verify compatibility with your setup
- Test in a staging environment first

### 3. Pin Specific Versions When Needed

For critical production services, consider:
- Pinning to specific versions
- Removing from auto-update config
- Manual updates with thorough testing

### 4. Use Dry-Run for Testing

Before deploying to production:
```bash
uv run python .github/scripts/update-versions.py --dry-run
```

Review the output to understand what would change.

### 5. Monitor Major Version Warnings

Watch for major version warnings in logs:
```
[INFO] New major available in library/postgres: 19.0
```

These require manual review and testing before upgrading.

## Contributing

This tooling is designed to be generic and reusable. Contributions welcome:

- Additional registry support
- Better variant detection
- Configuration validation
- Testing improvements

## License

This version updater is part of your GitOps repository and follows the same license.
