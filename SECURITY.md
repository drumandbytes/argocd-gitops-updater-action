# Security Policy

## Supported Versions

We provide security updates for the following versions:

| Version | Supported          |
| ------- | ------------------ |
| 2.x     | :white_check_mark: |
| 1.x     | :x:                |

We recommend always using the latest version of the action to ensure you have the most recent security fixes.

## Reporting a Vulnerability

We take security vulnerabilities seriously. If you discover a security issue, please report it responsibly.

### How to Report

**Please do NOT report security vulnerabilities through public GitHub issues.**

Instead, please send an email to **maris@drumandbytes.com** with:

1. **Description**: A clear description of the vulnerability
2. **Impact**: The potential impact of the vulnerability
3. **Steps to Reproduce**: Detailed steps to reproduce the issue
4. **Affected Versions**: Which versions are affected
5. **Suggested Fix**: If you have a suggested fix, please include it

### What to Expect

- **Acknowledgment**: We will acknowledge receipt of your report within 48 hours
- **Updates**: We will keep you informed of our progress
- **Resolution**: We aim to resolve critical vulnerabilities within 7 days
- **Credit**: With your permission, we will credit you in the security advisory

## Security Best Practices

When using this action, please follow these security practices:

### Secrets Management

- **Never commit secrets** to your repository
- **Use GitHub Secrets** for all sensitive values:
  - `DOCKERHUB_USERNAME` and `DOCKERHUB_TOKEN`
  - `SLACK_WEBHOOK_URL`
  - `TEAMS_WEBHOOK_URL`
  - `DISCORD_WEBHOOK_URL`
  - `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID`
- **Rotate credentials** periodically
- **Use minimal permissions** when creating access tokens

### Workflow Security

- **Pin action versions** to a specific version tag or commit SHA:
  ```yaml
  # Good - pinned to version
  uses: drumandbytes/argocd-gitops-updater-action@v2

  # Better - pinned to commit SHA
  uses: drumandbytes/argocd-gitops-updater-action@<commit-sha>
  ```
- **Review pull requests** created by the action before merging
- **Limit workflow permissions** to only what's needed:
  ```yaml
  permissions:
    contents: write
    pull-requests: write
  ```

### Registry Authentication

- Use **read-only tokens** when possible
- Create **dedicated service accounts** for CI/CD pipelines
- Enable **audit logging** on your container registries

## Security Features

This action includes several security features:

- **No credential logging**: Secrets are never logged or exposed in outputs
- **Sandboxed execution**: Runs in an isolated GitHub Actions environment
- **Input validation**: All inputs are validated before use
- **Minimal dependencies**: Reduces attack surface

## Vulnerability Disclosure Policy

We follow coordinated vulnerability disclosure:

1. Reporter submits vulnerability privately
2. We confirm and assess the issue
3. We develop and test a fix
4. We release the fix and publish a security advisory
5. Reporter may be credited (with permission)

## Contact

For security-related questions or concerns, contact **maris@drumandbytes.com**.

For general questions or bug reports, please use [GitHub Issues](https://github.com/drumandbytes/argocd-gitops-updater-action/issues).
