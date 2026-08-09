# legal-decisions-rag

Project to expose publicly available legal decisions to non-technical users through chat interfaces (Copilot etc.)

---

Modern Python project built with:

- **Package manager**: [uv](https://docs.astral.sh/uv/) for fast dependency management
- **Linting**: [Ruff](https://docs.astral.sh/ruff/) for code quality
- **Type checking**: [Ty](https://docs.astral.sh/ty/) for static analysis
- **Testing**: [pytest](https://docs.pytest.org/) for comprehensive testing
- **Task runner**: [just](https://github.com/casey/just) for project commands

## Installation

### Prerequisites

Install required tools:

**uv** (Python package manager):
```sh
# macOS/Linux
curl -LsSf https://astral.sh/uv/install.sh | sh

# Windows
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
```

**just** (command runner):
```sh
# macOS
brew install just

# Ubuntu/Debian
sudo apt update && sudo apt install just

# Other: https://github.com/casey/just#installation
```

### Project setup

1. **Clone the repository**:
```sh
git clone https://github.com/niels-tack/legal-decisions-rag.git
cd legal-decisions-rag
```

2. **Configure Python version**:

The project uses Python 3.13 as specified in `.python-version`. Tools like `pyenv`, `uv`, and `asdf` will automatically use this version.

3. **Install dependencies**:
```sh
just install
```

## Development

### Quick start

Run the application:
```sh
just run
```

Run tests:
```sh
just test
```

Check code quality (lint + type checking):
```sh
just check
```

### Available commands

Run `just` to see all available commands:

```sh
just --list
```

**Quality Assurance**:
- `just test [args]` - Run pytest tests
- `just lint [args]` - Run Ruff linter with auto-fix
- `just typing [args]` - Run Ty type checker
- `just check [args]` - Run both lint and typing
- `just security [args]` - Check for security vulnerabilities with pip-audit

**Lifecycle**:
- `just run` - Execute the main application
- `just install` - Sync dependencies with pyproject.toml
- `just update` - Update all dependencies to latest versions
- `just clean` - Remove cache and temporary files

### Development tools

The template includes modern Python tooling:

- **uv**: Fast package manager and project manager
- **ruff**: Lightning-fast linting and formatting
- **ty**: Type checking with pyright
- **pytest**: Testing framework with coverage
- **pip-audit**: Security vulnerability scanning
- **just**: Command runner (see `justfile` for all commands)

### Security scanning

The project includes automated security vulnerability scanning:

```sh
# Run security audit
just security

# Or run manually
uv run python -m pip_audit --skip-editable
```

The test suite includes `test_pypi_security_audit.py` which automatically checks for known vulnerabilities in dependencies. Known acceptable risks can be ignored by adding `--ignore-vuln CVE-XXXXX-XXXXX` flags.

### Environment variables

## Project context

The `/context` directory contains the **single source of truth** for project requirements:

- **`context/Functional requirements.md`** - Problem statement, target users, success criteria, and core requirements
- **`context/Technical requirements.md`** - Architecture, technology stack, constraints, and technical preferences

**⚠️ Important:** Keep these documents updated as the project evolves. AI coding assistants (like GitHub Copilot) reference these files to understand project scope and make appropriate code suggestions.

## Project structure

```
legal-decisions-rag/
├── context/               # Project requirements (single source of truth)
│   ├── Functional requirements.md
│   └── Technical requirements.md
├── src/                   # Application source code
│   ├── __init__.py
│   └── main.py           # Entry point
├── tests/                # Test files
│   └── test_main.py
├── .vscode/              # VS Code configuration
│   └── copilot-instructions.md  # AI assistant instructions
├── .env.example          # Example environment variables
├── .python-version       # Python version specification
├── .python-version        # Python version for this project
├── justfile               # Task runner commands
├── pyproject.toml         # Project metadata and dependencies
└── README.md              # This file
```

## Contributing

1. Create a feature branch: `git checkout -b feature/my-feature`
2. Make your changes and add tests
3. Run quality checks: `just check`
4. Run tests: `just test`
5. Commit and push: `git commit && git push`

## License

This project is licensed under the MIT License.

## Resources

- [uv documentation](https://docs.astral.sh/uv/)
- [Ruff documentation](https://docs.astral.sh/ruff/)
- [pytest documentation](https://docs.pytest.org/)
- [just documentation](https://just.systems/)
