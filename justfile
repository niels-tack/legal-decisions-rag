set dotenv-load

@_:
    just --list

[group('qa')]
test *args:
    uv run -m pytest -q 

[group('qa')]
security *args:
    uv run python -m pip_audit --ignore-vuln CVE-2025-53000 --skip-editable 

[group('qa')]
lint *args:
    uv run ruff check --fix  

[group('qa')]
typing *args:
    uv run ty check 

[group('qa')]
check *args:
    just lint 
    just typing 


run:
    uv run python -m src.main

# Remove temporary files
[group('lifecycle')]
clean:
    rm -rf .venv .pytest_cache .ruff_cache .uv-cache
    find . -type d -name "*.egg-info" -exec rm -rf {} +
    find . -type d -name "__pycache__" -exec rm -r {} +

# Update dependencies
[group('lifecycle')]
update:
    uv sync --upgrade

# Ensure project virtualenv is up to date
[group('lifecycle')]
install:
    uv sync

