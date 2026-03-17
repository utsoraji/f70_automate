# AGENTS.md

## Environment & Execution
- Project dependencies are expected to be installed in `.venv`.
- Python: `.venv\Scripts\python.exe`
- Execution: `.\.venv\Scripts\python.exe -m pytest` or `... -m src.main`
- All commands must be executed with `PYTHONPATH=src`.
- Example:
  PYTHONPATH=src; .\.venv\Scripts\python.exe -m pytest
  PYTHONPATH=src; .\.venv\Scripts\python.exe -m src.main

## Project Structure
- `src/f70_automate`: Application logic. Python import root.
- `src/f70_automate/test`: Unit and integration tests.
- `doc/`: Technical references and samples.

## Protocol & Type Safety Principles

- **Two Patterns of Abstraction**:
  1. **Consumer-Driven**: Define what the logic *needs*. Used for internal decoupling.
  2. **External-Driven (Adapters)**: Mirror the API of external libraries/SDKs. Used to enable **Mocking** of side-effect-heavy dependencies (e.g., Cloud SDKs, Databases).
- **Mandatory Mocking**: Every Protocol must have a corresponding `Mock` implementation in tests to ensure the logic can be verified without external side effects.
- **Verification**: Use `if TYPE_CHECKING:` to ensure concrete implementations (including external wrappers) don't drift from the Protocol.
- **Reference**: Strictly follow the coding pattern in `doc/samples/protocol_pattern.py`. Do not invent your own structure.
