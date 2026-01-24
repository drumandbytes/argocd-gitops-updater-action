# ArgoCD GitOps Updater Action

[![GitHub marketplace](https://img.shields.io/badge/marketplace-container--helm--version--updater-blue?logo=github)](https://github.com/marketplace/actions/container-helm-version-updater)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

> GitHub Action for automated Helm chart and Docker image version updates. GitOps-friendly with ArgoCD/Kustomize support, auto-discovery, semantic versioning, and notifications (Slack/Teams/Discord/Telegram)

Automatically keep your GitOps repositories up-to-date by checking for new versions of Helm charts and Docker images, creating pull requests with updates, and notifying your team.

## ✨ Features

- 🔄 **Automated Version Updates** - Automatically detect and update to latest semantic versions
- 🎯 **Variant Preservation** - Keeps image variants intact (alpine → alpine, slim → slim)
- 🔍 **Auto-Discovery** - Automatically find Helm charts and Docker images in your repo
- 📦 **Multi-Registry Support** - Docker Hub, ghcr.io, quay.io, gcr.io, and more
- 🚀 **Performance Optimized** - Concurrent processing and HTTP caching (5-10x speedup with caching enabled)
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
      - uses: actions/checkout@v6

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

### With Caching for Better Performance

```yaml
- uses: drumandbytes/argocd-gitops-updater-action@v1
  with:
    config-path: '.update-config.yaml'
    create-pr: true
    cache: true              # Enable registry API caching
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
| `cache` | Enable registry API response caching (~10-50 MB storage) | No | `false` |

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
      - uses: actions/checkout@v6

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

### Notifications with Built-in Support

**Recommended:** Use the action's built-in notification support for Slack, Discord, Microsoft Teams, or Telegram:

```yaml
- uses: drumandbytes/argocd-gitops-updater-action@v1
  with:
    config-path: '.update-config.yaml'
    create-pr: true
    # Built-in notification support - automatically sends formatted updates
    notification-method: slack
    slack-webhook-url: ${{ secrets.SLACK_WEBHOOK_URL }}
```

**Benefits of built-in notifications:**
- ✅ Automatically formatted with update details
- ✅ Includes PR links, operation status, and update summary
- ✅ No additional workflow steps needed
- ✅ Consistent formatting across all notification platforms

**Supported methods:** `slack`, `discord`, `microsoft-teams`, `telegram`, or `none`

See [Notification Examples](#-notification-examples) section below for detailed setup instructions for each platform.

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

### Performance: Enable Built-in Caching

**Highly Recommended!** Enable built-in caching to persist registry API responses between workflow runs (5-10x speedup):

```yaml
- uses: drumandbytes/argocd-gitops-updater-action@v1
  with:
    config-path: '.update-config.yaml'
    create-pr: true
    cache: true  # Enable caching for 5-10x performance improvement
```

That's it! Just add `cache: true` and the action handles everything automatically.

**How it works:**

1. **Cache restore:** When enabled, the action automatically restores `.registry_cache/` from previous workflow runs
2. **Action runs:** The updater script reads cached API responses and writes new responses to `.registry_cache/`
3. **Cache save:** The action explicitly saves `.registry_cache/` to GitHub Actions cache storage
4. **Automatic cleanup:** The cache directory is removed before change detection (never committed to your repository)

**Cache behavior:**
- **With `cache: true`:** Cache persists for up to 7 days between workflow runs in GitHub's cache storage
- **With `cache: false` (default):** Cache is lost after each workflow run (but action still works, just slower)
- **Cache key strategy:** Based on config file hash and run number for optimal cache hits
- **Script-level caching:** The Python script caches HTTP responses for 6 hours using SQLite

**Performance benefits:**
- **First run (no cache):** ~20-30s for 10 images (mostly HTTP request time)
- **Fully cached run (same day):** ~2-5s (5-10x faster, within 6-hour cache window)
- **Partially cached run (next day):** ~8-15s (2-3x faster, some cache expired after 6 hours)
- **Rate limit protection:** Dramatically fewer API calls to Docker Hub and other registries

**Important notes:**
- ✅ Cache is managed entirely by the action - no manual setup needed
- ✅ Cache is never committed to your repository (automatically cleaned up)
- ✅ No breaking changes - cache defaults to `false` for backward compatibility
- ✅ Free and built into GitHub Actions (no external services needed)

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

### Caching for Performance

Enable registry API response caching to reduce network requests and improve performance:

```yaml
- uses: drumandbytes/argocd-gitops-updater-action@v1
  with:
    config-path: '.update-config.yaml'
    cache: true              # Enable registry API caching (opt-in)
```

**Benefits:**
- Caches Docker Hub, GHCR, and other registry API responses (tag lists)
- Reduces redundant network calls within the 6-hour cache lifetime
- Storage: ~10-50 MB (negligible)
- Default: Disabled (opt-in to respect cache storage limits)

**Performance Impact:**
- Most workflows see minimal improvement from caching (a few seconds)
- Best for workflows that run multiple times within 6 hours
- Daily/weekly scheduled workflows may see limited benefit (cache expires)

**When to Disable:**
```yaml
cache: false  # Use when testing/debugging version detection
```

### Registry Rate Limits

| Registry | Anonymous | Authenticated | Concurrent Limit |
|----------|-----------|---------------|------------------|
| Docker Hub | 100 req/6h | 200 req/6h | 3 (anon) / 5 (auth) |
| ghcr.io | Limited | 5,000 req/h | 10 |
| quay.io | ~100 req/min | Higher | 5 |
| gcr.io | No strict limit | - | 5 |

**Tip**: Enable `cache: true` to reduce API calls and stay well within rate limits.

### Performance Features

- **HTTP Caching**: 6-hour SQLite cache for registry API responses
- **Concurrent Processing**: Up to 10 parallel workers for image updates
- **Smart Rate Limiting**: Per-registry semaphores prevent API throttling
- **GitHub Actions Cache**: Persistent cache between workflow runs (opt-in)

## 🎯 Supported Registries

- ✅ Docker Hub (`dockerhub`, `docker.io`)
- ✅ GitHub Container Registry (`ghcr.io`)
- ✅ Quay.io (`quay.io`)
- ✅ Google Container Registry (`gcr.io`)
- ✅ Amazon ECR (public)
- ✅ Custom registries with standard APIs

## 📝 Notification Examples

**The action has built-in notification support** - no need to use external notification actions! Simply configure the appropriate webhook URL and notification method in the action inputs.

All notifications automatically include:
- 📦 Update completion status
- 🔌 Pull request link and number
- ⚙️ Operation type (created/updated)
- 📝 PR title
- 📋 Detailed update summary

### Slack

**Prerequisites:** You need a Slack workspace. If you don't have one, create at https://slack.com/create

**Create Incoming Webhook:**

1. Go to https://api.slack.com/messaging/webhooks
2. Click "Create your Slack app" → "From scratch"
3. Name your app (e.g., "Version Updater") and select your workspace
4. Click "Incoming Webhooks" → Toggle "Activate Incoming Webhooks" to ON
5. Click "Add New Webhook to Workspace"
6. Select the channel where notifications will be posted → Click "Allow"
7. Copy the webhook URL (starts with `https://hooks.slack.com/services/...`)

**Add to GitHub Secrets:**
- Repository Settings → Secrets and variables → Actions → New repository secret
- Name: `SLACK_WEBHOOK_URL`
- Value: Your webhook URL

**Use in workflow:**
```yaml
notification-method: slack
slack-webhook-url: ${{ secrets.SLACK_WEBHOOK_URL }}
```

### Microsoft Teams

> **⚠️ Note:** Microsoft Teams support is implemented according to the official Microsoft Teams Incoming Webhook API documentation but has not been personally tested by the maintainer due to Teams Free tier limitations. The implementation follows the same pattern as other notification platforms (Slack, Discord, Telegram) which have been tested. If you encounter issues, please [report them](https://github.com/drumandbytes/argocd-gitops-updater-action/issues).

**Prerequisites:** You need Microsoft Teams with a team and channel (work/school account). Free tier may have limitations.

**Create Incoming Webhook:**

1. Open Microsoft Teams and go to your channel (e.g., "General")
2. Click "..." (three dots) next to the channel name
3. Select "Workflows" or "Connectors" (depends on Teams version):
   - **New Teams:** Search for "Incoming Webhook" → Add → Configure → Copy webhook URL
   - **Classic Teams:** Select "Incoming Webhook" → Configure → Name it → Create → Copy webhook URL

**Add to GitHub Secrets:**
- Repository Settings → Secrets and variables → Actions → New repository secret
- Name: `TEAMS_WEBHOOK_URL`
- Value: Your webhook URL

**Use in workflow:**
```yaml
notification-method: microsoft-teams
teams-webhook-url: ${{ secrets.TEAMS_WEBHOOK_URL }}
```

### Discord

**Prerequisites:** You need a Discord server. If you don't have one, create at https://discord.com

**Create Webhook:**

1. Right-click on the channel where you want notifications → "Edit Channel"
2. Go to "Integrations" → "Webhooks"
3. Click "New Webhook" or "Create Webhook"
4. Give it a name (e.g., "Version Updater") and optionally upload an avatar
5. Click "Copy Webhook URL"
6. Click "Save Changes"

**Add to GitHub Secrets:**
- Repository Settings → Secrets and variables → Actions → New repository secret
- Name: `DISCORD_WEBHOOK_URL`
- Value: Your webhook URL

**Use in workflow:**
```yaml
notification-method: discord
discord-webhook-url: ${{ secrets.DISCORD_WEBHOOK_URL }}
```

### Telegram

**Create a bot:**

1. Open Telegram and search for `@BotFather`
2. Send `/newbot` and follow prompts to choose a name and username
3. Copy the **bot token** (looks like `123456789:ABCdefGhIJKlmNoPQRsTUVwxyZ`)

**Get your chat ID:**

- **For personal chat:** Search for `@userinfobot` → Send any message → Copy your chat ID
- **For group chat:** Add your bot to a group → Add `@userinfobot` temporarily → Send a message → Copy the group chat ID (negative number) → Remove `@userinfobot`

**Add to GitHub Secrets:**
- Repository Settings → Secrets and variables → Actions → New repository secret
- Name: `TELEGRAM_BOT_TOKEN` (paste the bot token)
- Name: `TELEGRAM_CHAT_ID` (paste the chat ID)

**Use in workflow:**
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
