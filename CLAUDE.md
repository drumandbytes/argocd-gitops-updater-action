# CLAUDE.md

## Project Overview

`argocd-gitops-updater-action` is a GitHub composite action (Marketplace: "Container & Helm Version Updater") that scans a GitOps repo's `.update-config.yaml`, checks Docker/Helm registries for newer versions, rewrites the matching YAML files, and opens a PR. All logic lives in two scripts run by `action.yml`: `.github/scripts/update-versions.py` (core update logic, ~1500 lines) and `.github/scripts/discover-resources.py` (auto-discovery of Helm charts/images from ArgoCD Applications, Kustomize, and manifests, ~560 lines). See [README.md](README.md) for the user-facing config schema and [examples/](examples/) for working caller workflows (basic, auto-discovery, multi-notification, advanced).

## Action Contract

`action.yml` is the API — read it directly for the full input/output list rather than trusting this summary. Key points not obvious from a skim:
- `create-pr` uses `peter-evans/create-pull-request`; PR creation is skipped entirely in `dry-run` mode.
- When `auto-discover: true` finds new resources, it opens a *separate* discovery PR and the run stops there (`exit 0`) — version updates only happen on a subsequent run, after that PR is reviewed/merged.
- Notifications (Slack/Teams/Discord/Telegram) are independent, all-optional, fire-and-forget (`|| echo "Failed to send..."` — a bad webhook never fails the job).

## Local Dev

```bash
pip install aiohttp aiofiles pyyaml packaging pytest pytest-asyncio ruff
pytest tests/ -v
ruff check .github/scripts/
ruff format --check .github/scripts/
```

CI (`drumandbytes/reusable-actions/.github/workflows/python-action-ci.yml`) gates on all three: `ruff check`, `ruff format --check`, and `pytest`. Running `ruff check` alone can pass locally while CI still fails on formatting — always run `ruff format --check` (or just `ruff format`) before pushing.

## Release

release-please owns `version.txt`, `.release-please-manifest.json`, and `CHANGELOG.md` — never hand-edit them. Squash-merge PRs with Conventional Commits titles (`feat:`, `fix:`, `feat!:`/`BREAKING CHANGE:`); `chore:`/`docs:`/`ci:`/`test:` don't trigger a release. Merging the release-please PR cuts the release and moves the floating `v2`/`v2.N` tags. Patch-only release-please PRs (author `dnb-robot[bot]`) auto-merge via `auto-merge.yml`.
