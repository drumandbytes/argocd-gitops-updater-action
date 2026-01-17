# ArgoCD GitOps Updater Action

[![GitHub marketplace](https://img.shields.io/badge/marketplace-argocd--gitops--updater--action-blue?logo=github)](https://github.com/marketplace/actions/argocd-gitops-updater-action)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

> GitHub Action for automated Helm chart and Docker image version updates. GitOps-friendly with ArgoCD/Kustomize support, auto-discovery, semantic versioning, and notifications (Slack/Teams/Discord/Telegram)

Automatically keep your GitOps repositories up-to-date by checking for new versions of Helm charts and Docker images, creating pull requests with updates, and notifying your team.

## ✨ Features

- 🔄 **Automated Version Updates** - Automatically detect and update to latest semantic versions
- 🎯 **Variant Preservation** - Keeps image variants intact (alpine → alpine, slim → slim)
- 🔍 **Auto-Discovery** - Automatically find Helm charts and Docker images in your repo
- 📦 **Multi-Registry Support** - Docker Hub, ghcr.io, quay.io, gcr.io, and more
- 🚀 **Performance Optimized** - Concurrent processing and HTTP caching (7-10x speedup)
- 🔒 **Rate Limit Management** - Per-registry rate limiting with authentication support
- 📊 **Smart Notifications** - Slack, Microsoft Teams, Discord, Telegram support
- ⚠️ **Major Version Alerts** - Get notified when major version updates are available
- 🚫 **Ignore Rules** - Blacklist specific images/charts or versions with regex patterns
- 🏷️ **Semantic Versioning** - Intelligent version comparison and updates
- 🔐 **GitOps Native** - Works with ArgoCD Applications and Kustomize

## 🚀 Quick Start

### Basic Usage

```yaml
name: Update Versions

on:
  schedule:
    - cron: '0 2 * * 1'  # Every Monday at 2 AM
  workflow_dispatch:

jobs:
  update:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - uses: drumandbytes/argocd-gitops-updater-action@v1
        with:
          config-path: '.update-config.yaml'
          create-pr: true
```

### With Auto-Discovery

```yaml
- uses: drumandbytes/argocd-gitops-updater-action@v1
  with:
    auto-discover: true
    create-pr: true
    pr-title: 'chore: update dependencies'
```

### With Docker Hub Authentication

```yaml
- uses: drumandbytes/argocd-gitops-updater-action@v1
  with:
    config-path: '.update-config.yaml'
    dockerhub-username: ${{ secrets.DOCKERHUB_USERNAME }}
    dockerhub-token: ${{ secrets.DOCKERHUB_TOKEN }}
    create-pr: true
```

### With Notifications

```yaml
- uses: drumandbytes/argocd-gitops-updater-action@v1
  with:
    config-path: '.update-config.yaml'
    create-pr: true
    notification-method: slack
    slack-webhook-url: ${{ secrets.SLACK_WEBHOOK_URL }}
```

## 📋 Configuration File

You can either **create `.update-config.yaml` manually** or **use auto-discovery to generate it automatically**.

### Manual Configuration

Create `.update-config.yaml` in your repository:

```yaml
# Helm Charts
helmCharts:
  - name: prometheus
    repository: https://prometheus-community.github.io/helm-charts
    chartName: prometheus
    # Path to the file containing the version
    files:
      - path: apps/monitoring/prometheus/Chart.yaml
        versionKey: dependencies[0].version

  - name: grafana
    repository: https://grafana.github.io/helm-charts
    chartName: grafana
    files:
      - path: apps/monitoring/grafana/kustomization.yaml
        versionKey: helmCharts[0].version

# Docker Images
dockerImages:
  - id: postgres-primary
    repository: postgres
    registry: dockerhub
    currentTag: "16.1-alpine"
    files:
      - path: apps/database/deployment.yaml
        imageKey: spec.template.spec.containers[0].image

  - id: redis
    repository: redis
    registry: dockerhub
    currentTag: "7.2-alpine"
    files:
      - path: apps/cache/deployment.yaml
        imageKey: spec.template.spec.containers[0].image

# Ignore certain updates (optional)
ignore:
  dockerImages:
    # Ignore by ID
    - id: postgres-primary

    # Ignore by repository and tag pattern
    - repository: nginx
      tagPattern: "^.*-perl$"  # Ignore all perl variants

  helmCharts:
    # Ignore by name
    - name: legacy-chart

    # Ignore specific version patterns
    - name: prometheus
      versionPattern: "^25\\."  # Ignore version 25.x
```

### Auto-Discovery (Recommended for Getting Started)

**Don't want to create the config manually?** Use auto-discovery:

```yaml
- uses: drumandbytes/argocd-gitops-updater-action@v1
  with:
    auto-discover: true
    create-pr: true
```

This will:
1. Automatically scan your repository for:
   - ArgoCD Applications with Helm charts
   - Kustomize files with Helm chart references
   - Kubernetes manifests with Docker images
2. Generate `.update-config.yaml` with all discovered resources
3. Create a PR with the generated config
4. **Stop before running updates** (you review and merge the config first)

After merging the auto-discovery PR, subsequent runs will use the config file for updates. You can run auto-discovery periodically to find new resources, or disable it and only use the existing config.

See [Auto-Discovery Workflow](#auto-discovery-workflow) for a complete example.

## 📖 Inputs

| Input | Description | Required | Default |
|-------|-------------|----------|---------|
| `config-path` | Path to the update configuration YAML file | No | `.update-config.yaml` |
| `auto-discover` | Auto-discover resources before updating | No | `false` |
| `working-directory` | Working directory for the action | No | `.` |
| `create-pr` | Create a pull request with changes | No | `true` |
| `pr-title` | Title for the pull request | No | `chore: update Helm charts & Docker images` |
| `pr-branch` | Branch name for the pull request | No | `chore/update-versions` |
| `pr-base` | Base branch for the pull request | No | `main` |
| `commit-message` | Commit message for changes | No | `chore: update Helm charts & Docker images` |
| `dry-run` | Run in dry-run mode without making changes | No | `false` |
| `python-version` | Python version to use | No | `3.12` |
| `notification-method` | Notification method: `telegram`, `slack`, `microsoft-teams`, `discord`, or `none` | No | `none` |
| `telegram-bot-token` | Telegram bot token for notifications | No | - |
| `telegram-chat-id` | Telegram chat ID for notifications | No | - |
| `slack-webhook-url` | Slack webhook URL for notifications | No | - |
| `teams-webhook-url` | Microsoft Teams webhook URL for notifications | No | - |
| `discord-webhook-url` | Discord webhook URL for notifications | No | - |
| `dockerhub-username` | Docker Hub username (increases rate limit 100→200 req/6h) | No | - |
| `dockerhub-token` | Docker Hub access token | No | - |
| `github-token` | GitHub token for ghcr.io authentication | No | `${{ github.token }}` |

## 📤 Outputs

| Output | Description |
|--------|-------------|
| `discovery-changes-detected` | Whether auto-discovery found new resources (`true`/`false`) |
| `discovery-pr-number` | Discovery pull request number (if created) |
| `discovery-pr-url` | Discovery pull request URL (if created) |
| `changes-detected` | Whether any version update changes were detected (`true`/`false`) |
| `update-report` | Summary report of updates made |
| `pr-number` | Version update pull request number (if created) |
| `pr-url` | Version update pull request URL (if created) |

## 🔧 Advanced Usage

### Auto-Discovery Workflow

Automatically discover all Helm charts and Docker images in your repository:

```yaml
name: Discover Resources

on:
  workflow_dispatch:

jobs:
  discover:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - uses: drumandbytes/argocd-gitops-updater-action@v1
        with:
          auto-discover: true
          create-pr: true
          pr-title: 'chore: auto-discover new resources'
```

This will:
1. Scan your repository for ArgoCD Applications, Kustomize files, and Kubernetes manifests
2. Extract Helm charts and Docker images
3. Create a PR with updated `.update-config.yaml`
4. Stop before running version updates (you review and merge first)

### Dry Run Mode

Test without making changes:

```yaml
- uses: drumandbytes/argocd-gitops-updater-action@v1
  with:
    config-path: '.update-config.yaml'
    dry-run: true
```

### Multiple Notification Channels

```yaml
- uses: drumandbytes/argocd-gitops-updater-action@v1
  with:
    config-path: '.update-config.yaml'
    create-pr: true

# Send Slack notification
- name: Notify Slack
  if: steps.update.outputs.changes-detected == 'true'
  uses: slackapi/slack-github-action@v1
  with:
    webhook: ${{ secrets.SLACK_WEBHOOK }}
    payload: |
      {
        "text": "Version updates available: ${{ steps.update.outputs.pr-url }}"
      }
```

### Using Outputs

```yaml
- uses: drumandbytes/argocd-gitops-updater-action@v1
  id: updater
  with:
    config-path: '.update-config.yaml'
    create-pr: true

- name: Comment on issue
  if: steps.updater.outputs.changes-detected == 'true'
  uses: actions/github-script@v7
  with:
    script: |
      github.rest.issues.create({
        owner: context.repo.owner,
        repo: context.repo.repo,
        title: 'Version Updates Available',
        body: `${{ steps.updater.outputs.update-report }}`
      });
```

### Performance: Using GitHub Actions Cache

**Highly Recommended!** Add caching to dramatically improve performance (7-10x speedup, 40x for fully cached runs):

```yaml
steps:
  - name: Checkout repository
    uses: actions/checkout@v4

  # Add this cache step BEFORE the updater action
  - name: Cache registry API responses
    uses: actions/cache@v4
    with:
      path: .registry_cache
      key: registry-cache-${{ hashFiles('.update-config.yaml') }}-${{ github.run_number }}
      restore-keys: |
        registry-cache-${{ hashFiles('.update-config.yaml') }}-
        registry-cache-

  - name: Update versions
    uses: drumandbytes/argocd-gitops-updater-action@v1
    with:
      config-path: '.update-config.yaml'
      create-pr: true
```

**How it works:**
- The action caches HTTP responses from Docker Hub, ghcr.io, etc. in `.registry_cache/`
- Without GitHub Actions cache: This directory is lost after each workflow run
- With GitHub Actions cache: The directory persists between runs for 7 days
- **Cache key strategy:**
  - Primary key includes config file hash and run number
  - Restore-keys allow using previous cache even if config changed
- **Result:** Registry API calls are cached for 6 hours, dramatically reducing requests

**Cache benefits:**
- **First run:** Normal speed (no cache)
- **Second run (same day):** 40x faster (fully cached)
- **Second run (next day):** 7-10x faster (partial cache, 6-hour expiration)
- **Avoids rate limits:** Fewer API calls to Docker Hub and other registries

## 🔐 Authentication Setup

### Docker Hub (Recommended)

Increase rate limits from 100 to 200 requests per 6 hours:

1. Create access token at https://hub.docker.com/settings/security
2. Add to repository secrets:
   - `DOCKERHUB_USERNAME`
   - `DOCKERHUB_TOKEN`
3. Use in workflow:

```yaml
- uses: drumandbytes/argocd-gitops-updater-action@v1
  with:
    dockerhub-username: ${{ secrets.DOCKERHUB_USERNAME }}
    dockerhub-token: ${{ secrets.DOCKERHUB_TOKEN }}
```

### GitHub Container Registry (ghcr.io)

The action automatically uses `${{ github.token }}` for ghcr.io authentication. For custom tokens:

```yaml
- uses: drumandbytes/argocd-gitops-updater-action@v1
  with:
    github-token: ${{ secrets.CUSTOM_GITHUB_TOKEN }}
```

## 📊 Performance & Rate Limits

### Registry Rate Limits

| Registry | Anonymous | Authenticated | Concurrent Limit |
|----------|-----------|---------------|------------------|
| Docker Hub | 100 req/6h | 200 req/6h | 3 (anon) / 5 (auth) |
| ghcr.io | Limited | 5,000 req/h | 10 |
| quay.io | ~100 req/min | Higher | 5 |
| gcr.io | No strict limit | - | 5 |

### Performance Features

- **HTTP Caching**: 6-hour SQLite cache for registry API responses
- **Concurrent Processing**: Up to 10 parallel workers for image updates
- **Smart Rate Limiting**: Per-registry semaphores prevent API throttling
- **GitHub Actions Cache**: Persistent cache between workflow runs

**Performance**: Typically 7-10x faster with caching enabled (40x for fully cached runs).

## 🎯 Supported Registries

- ✅ Docker Hub (`dockerhub`, `docker.io`)
- ✅ GitHub Container Registry (`ghcr.io`)
- ✅ Quay.io (`quay.io`)
- ✅ Google Container Registry (`gcr.io`)
- ✅ Amazon ECR (public)
- ✅ Custom registries with standard APIs

## 📝 Notification Examples

### Slack

Create webhook at: https://api.slack.com/messaging/webhooks

```yaml
notification-method: slack
slack-webhook-url: ${{ secrets.SLACK_WEBHOOK_URL }}
```

### Microsoft Teams

Create webhook in Teams channel settings:

```yaml
notification-method: microsoft-teams
teams-webhook-url: ${{ secrets.TEAMS_WEBHOOK_URL }}
```

### Discord

Create webhook in channel settings → Integrations:

```yaml
notification-method: discord
discord-webhook-url: ${{ secrets.DISCORD_WEBHOOK_URL }}
```

### Telegram

1. Create bot with @BotFather
2. Get chat ID from @userinfobot
3. Configure:

```yaml
notification-method: telegram
telegram-bot-token: ${{ secrets.TELEGRAM_BOT_TOKEN }}
telegram-chat-id: ${{ secrets.TELEGRAM_CHAT_ID }}
```

## 🛠️ Troubleshooting

### Rate Limit Errors (429)

**Problem**: Too many requests to Docker Hub

**Solution**:
1. **Add caching** - See [Performance: Using GitHub Actions Cache](#performance-using-github-actions-cache) section above
2. **Add Docker Hub authentication** - Doubles rate limit from 100 to 200 requests per 6 hours (see [Authentication Setup](#-authentication-setup))
3. **Reduce update frequency** - Run weekly instead of daily (change `cron` schedule)

### Major Version Not Updating

This is by design. The action only updates within the same major version for safety. Major version updates are reported in notifications but require manual intervention.

### Auto-Discovery Not Finding Resources

**Check**:
1. Resources are in standard ArgoCD/Kustomize formats
2. YAML files have correct structure
3. Run with `dry-run: true` to see what's being processed

### PR Creation Fails

**Common causes**:
1. No changes detected (check with `dry-run: true` first)
2. Missing permissions (add `contents: write` and `pull-requests: write`)
3. Branch already exists (configure `pr-branch` with unique name)

## 🤝 Contributing

Contributions welcome! Please feel free to submit issues or pull requests.

## 📄 License

MIT License - see [LICENSE](LICENSE) file for details

## 🔗 Links

- [Documentation](https://github.com/drumandbytes/argocd-gitops-updater-action/blob/main/docs/VERSION_UPDATER.md)
- [Issue Tracker](https://github.com/drumandbytes/argocd-gitops-updater-action/issues)
- [Changelog](https://github.com/drumandbytes/argocd-gitops-updater-action/releases)

## ⭐ Show Your Support

If this action helps you, please consider giving it a star! ⭐
