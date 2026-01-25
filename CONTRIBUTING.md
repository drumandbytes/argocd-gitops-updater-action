# Contributing to Container & Helm Version Updater

Thank you for your interest in contributing! This document provides guidelines and instructions for contributing.

## Development Setup

### Prerequisites

- Python 3.11 or higher
- pip

### Local Setup

1. Clone the repository:
   ```bash
   git clone https://github.com/drumandbytes/argocd-gitops-updater-action.git
   cd argocd-gitops-updater-action
   ```

2. Install dependencies:
   ```bash
   pip install aiohttp aiofiles pyyaml packaging pytest pytest-asyncio ruff
   ```

3. Run tests:
   ```bash
   pytest tests/ -v
   ```

4. Run linting:
   ```bash
   ruff check .github/scripts/
   ruff format --check .github/scripts/
   ```

## Project Structure

```
.
├── action.yml                    # GitHub Action definition
├── .github/
│   ├── scripts/
│   │   ├── update-versions.py    # Core version update logic
│   │   └── discover-resources.py # Auto-discovery logic
│   └── workflows/
│       └── ci.yml                # CI pipeline
├── tests/                        # Unit tests
├── examples/                     # Example configurations
└── README.md                     # User documentation
```

## Making Changes

### Code Style

- Follow PEP 8 guidelines
- Use type hints for function parameters and return values
- Keep functions focused and well-documented
- Use async/await for I/O operations

### Testing

- Add tests for new functionality
- Ensure all existing tests pass
- Test edge cases and error conditions

Run tests with:
```bash
pytest tests/ -v
```

### Linting

We use Ruff for linting and formatting:
```bash
# Check for issues
ruff check .github/scripts/

# Auto-fix issues
ruff check --fix .github/scripts/

# Check formatting
ruff format --check .github/scripts/

# Auto-format
ruff format .github/scripts/
```

## Submitting Changes

### Pull Request Process

1. Fork the repository
2. Create a feature branch: `git checkout -b feature/my-feature`
3. Make your changes
4. Run tests and linting
5. Commit with a clear message: `git commit -m "feat: add new feature"`
6. Push to your fork: `git push origin feature/my-feature`
7. Open a Pull Request

### Commit Message Format

Use conventional commit format:

- `feat:` - New features
- `fix:` - Bug fixes
- `docs:` - Documentation changes
- `refactor:` - Code refactoring
- `test:` - Adding or updating tests
- `chore:` - Maintenance tasks
- `perf:` - Performance improvements

Examples:
```
feat: add support for Azure Container Registry
fix: handle timeout errors in Docker Hub API
docs: update README with new configuration options
```

### Pull Request Guidelines

- Keep PRs focused on a single change
- Update documentation if needed
- Add tests for new functionality
- Ensure CI passes before requesting review

## Reporting Issues

When reporting bugs, please include:

1. **Description**: Clear description of the issue
2. **Steps to Reproduce**: How to reproduce the problem
3. **Expected Behavior**: What you expected to happen
4. **Actual Behavior**: What actually happened
5. **Environment**: Python version, OS, relevant configuration
6. **Logs**: Relevant error messages or logs

## Feature Requests

For feature requests:

1. Check existing issues to avoid duplicates
2. Describe the use case
3. Explain the expected behavior
4. Consider if it aligns with project goals

## Questions?

If you have questions, feel free to open an issue with the "question" label.

## License

By contributing, you agree that your contributions will be licensed under the MIT License.
