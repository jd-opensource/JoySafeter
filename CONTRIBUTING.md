# Contributing to JoySafeter

First off, thank you for considering contributing to JoySafeter! It's people like you that make this project better for everyone.

## Table of Contents

- [Code of Conduct](#code-of-conduct)
- [Getting Started](#getting-started)
- [Development Setup](#development-setup)
- [How to Contribute](#how-to-contribute)
- [Pull Request Process](#pull-request-process)
- [Coding Standards](#coding-standards)
- [Commit Guidelines](#commit-guidelines)
- [Issue Guidelines](#issue-guidelines)

## Code of Conduct

This project and everyone participating in it is governed by our [Code of Conduct](CODE_OF_CONDUCT.md). By participating, you are expected to uphold this code. Please report unacceptable behavior to the project maintainers.

## Getting Started

1. **Fork the repository** on GitHub
2. **Clone your fork** locally:
   ```bash
   git clone https://github.com/YOUR-USERNAME/JoySafeter.git
   cd JoySafeter
   ```
3. **Add the upstream remote**:
   ```bash
   git remote add upstream https://github.com/jd-opensource/JoySafeter.git
   ```

## Development Setup

Use the repository development guide instead of maintaining a second setup procedure here:

```bash
cd deploy
./local-test.sh
```

See [`DEVELOPMENT.md`](DEVELOPMENT.md) for prerequisites, component commands, tests, formatting,
and database migrations. Full-stack installation and deployment use
[`deploy/deploy.sh`](deploy/README.md).

## How to Contribute

### Reporting Bugs

Before creating bug reports, please check existing issues to avoid duplicates. When creating a bug report, include:

- **Clear title** describing the issue
- **Steps to reproduce** the behavior
- **Expected behavior** vs actual behavior
- **Screenshots** if applicable
- **Environment details** (OS, Python/Node versions, etc.)

### Suggesting Enhancements

Enhancement suggestions are tracked as GitHub issues. When creating an enhancement suggestion, include:

- **Clear title** describing the suggestion
- **Detailed description** of the proposed functionality
- **Use case** explaining why this would be useful
- **Possible implementation** approach (optional)

### Your First Code Contribution

Unsure where to begin? Look for issues labeled:

- `good first issue` - Simple issues for newcomers
- `help wanted` - Issues needing community help
- `documentation` - Documentation improvements

## Pull Request Process

1. **Create a feature branch** from `main`:
   ```bash
   git checkout -b feature/your-feature-name
   ```

2. **Make your changes** following our coding standards

3. **Write/update tests** for your changes

4. **Run tests, linters, and pre-commit hooks** — all commands live in
   [Development Guide – Tests and Quality Checks](DEVELOPMENT.md#tests-and-quality-checks).
   CI runs the same checks.

5. **Commit your changes** following our commit guidelines

6. **Push to your fork**:
   ```bash
   git push origin feature/your-feature-name
   ```

7. **Open a Pull Request** with:
   - Clear description of changes
   - Link to related issue(s)
   - Screenshots for UI changes

## Coding Standards

### Python (Backend)

- Follow [PEP 8](https://pep8.org/) style guide
- Use type hints for all functions
- Write docstrings for public functions and classes
- Keep functions focused and under 50 lines when possible
- Use `ruff` for linting and formatting

```python
# Good example
def process_message(message: str, user_id: int) -> ProcessedMessage:
    """
    Process an incoming message from a user.

    Args:
        message: The raw message content
        user_id: The ID of the user sending the message

    Returns:
        A ProcessedMessage object with parsed content

    Raises:
        ValidationError: If the message format is invalid
    """
    # Implementation
```

### TypeScript (Frontend)

- Use TypeScript strict mode
- Define interfaces for all props and state
- Use functional components with hooks
- Follow React best practices
- Use ESLint and Prettier for code quality

```typescript
// Good example
interface MessageProps {
  content: string;
  timestamp: number;
  onAction?: (action: string) => void;
}

export function Message({ content, timestamp, onAction }: MessageProps) {
  // Implementation
}
```

### General Guidelines

- Write self-documenting code with clear variable/function names
- Add comments for complex logic, not obvious code
- Keep files focused and under 500 lines when possible
- Don't commit commented-out code
- Remove console.log/print statements before committing

## Commit Guidelines

We follow [Conventional Commits](https://www.conventionalcommits.org/):

```
<type>(<scope>): <description>

[optional body]

[optional footer(s)]
```

### Types

- `feat`: New feature
- `fix`: Bug fix
- `docs`: Documentation changes
- `style`: Code style changes (formatting, etc.)
- `refactor`: Code refactoring
- `test`: Adding or updating tests
- `chore`: Maintenance tasks

### Examples

```bash
# Feature
feat(agent): add memory summarization strategy

# Bug fix
fix(api): handle null response in chat endpoint

# Documentation
docs(readme): update installation instructions

# Refactor
refactor(core): extract common validation logic
```

## Issue Guidelines

### Bug Report Template

```markdown
**Describe the bug**
A clear description of what the bug is.

**To Reproduce**
Steps to reproduce:
1. Go to '...'
2. Click on '...'
3. See error

**Expected behavior**
What you expected to happen.

**Screenshots**
If applicable, add screenshots.

**Environment:**
- OS: [e.g., macOS 14.0]
- Browser: [e.g., Chrome 120]
- Python: [e.g., 3.12.1]
- Node: [e.g., 20.10.0]
```

### Feature Request Template

```markdown
**Is your feature request related to a problem?**
A clear description of the problem.

**Describe the solution you'd like**
A clear description of what you want to happen.

**Describe alternatives you've considered**
Alternative solutions or features you've considered.

**Additional context**
Any other context or screenshots.
```

## Questions?

Feel free to open a discussion or reach out to the maintainers if you have questions about contributing.

Thank you for contributing! 🎉
