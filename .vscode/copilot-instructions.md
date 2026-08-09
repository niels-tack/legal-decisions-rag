# Python coding conventions for legal-decisions-rag

## ⚠️ Critical: Project context documents

**Always read these first** before making any code changes or architectural decisions:

- **`/context/Functional requirements.md`** - Single source of truth for:
  - Problem statement and target users
  - Success criteria and measurable outcomes
  - Core requirements (must have, should have, could have)
  - User workflows and acceptance criteria
  
- **`/context/Technical requirements.md`** - Single source of truth for:
  - Technical architecture and constraints
  - Technology stack and dependencies
  - Performance requirements and limitations
  - Security and compliance requirements
  - Integration points and APIs

**⚡ These documents define the project scope and boundaries.** Any code you write must align with these requirements. If you encounter a conflict or gap in the requirements, flag it for clarification rather than making assumptions.

## Python instructions

- Write clear and concise comments for each function.
- Ensure functions have descriptive names and include **type hints**.
- Provide **docstrings** following PEP 257 conventions, using the **Google style**:

```python
import math

def calculate_area(radius: float) -> float:
    """
    Calculate the area of a circle given the radius.

    Args:
        radius (float): The radius of the circle.

    Returns:
        float: The area of the circle, calculated as π * radius^2.
    """
    return math.pi ** 2
```

- Break down complex functions into smaller, manageable functions.
- Use the `typing` module for type annotations (e.g., `List[str]`, `Dict[str, int]`).
- Adhere to **modular design**, separation of concerns, and the **single responsibility principle**.
- Keep it simple: KISS (Keep It Simple, Stupid).

## Documentation style

- **Headings and Bold Text**: Use sentence case. Do not use capitals in headings or bold print, except for the first character (e.g., "Context & aims", "**Simple rules**").
- **Readability**: Avoid excessive capitalization to improve readability.

## General instructions

- Always prioritize readability, clarity, and maintainability.
- Include explanations of algorithms and design decisions in comments.
- Handle **edge cases** and implement robust exception handling.
- Write code for **production environments**, focusing on reliability, performance, and security.
- Mention libraries or external dependencies with comments explaining their purpose.
- Follow consistent naming conventions and language-specific best practices.
- **Partial success is not acceptable**: aim for 100% passing tests; do not accept “almost done” results.

## Task running & package management

- Use **just** as the primary task runner for workflows. See `justfile` for recipes.
- Use **uv** for package management.

```bash
just run        # Run the application
just test       # Run tests
just check      # Run linting and type checking
uv add <pkg>    # Add a dependency
```

## Code style, linting, and typing

- **Linting**: Adhere strictly to **ruff** configuration in `pyproject.toml`.
    - Line length: **88 characters**.
    - Rules: E, F, I (isort), B (bugbear), UP (pyupgrade).
    - Run `just lint` to check and fix issues.
- **Type Checking**: Adhere to **ty** configuration.
    - Strict type checking is enforced for `src/`.
    - Run `just typing` to verify types.
- **Formatting**: Follow **PEP 8** and **ruff format**.
    - Place function and class docstrings immediately after the `def` or `class` keyword.
    - 4-space indentation.
    - Double quotes for strings.
    - Use blank lines to separate functions, classes, and logical code blocks.

## Testing and edge cases

- Write **unit tests** for all new functionality using `pytest` and `pytest-asyncio`.
- Test **critical paths and edge cases**, including empty inputs, invalid types, and large datasets.
- Document tests with docstrings explaining what is being tested and why.
- Ensure **100% test coverage**; partial success is unacceptable.
- **Security testing** is included via `pip-audit` in `tests/test_pypi_security_audit.py` to detect known vulnerabilities.

## Autonomous verification

**You must autonomously verify your code.** Do not ask the user to run checks for you.
After creating or modifying any code, ALWAYS run the following commands in the terminal to ensure quality:

1.  **Linting & Type Checking**:
    ```bash
    just check
    ```
    *Fix any errors reported by ruff or ty immediately.*

2.  **Testing**:
    ```bash
    just test
    ```
    *Ensure all tests pass. If tests fail, analyze the failure and fix the code or the test.*

**Definition of done**:
- Code is written.
- `just check` passes (no linting or type errors).
- `just test` passes (all tests green).

