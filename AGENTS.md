# AGENTS.md

## Environment
- Python commands must use `.venv\Scripts\python.exe`.
- Tests must run inside the local `.venv` environment.
- Prefer module execution through the venv interpreter, for example:
  - `.\.venv\Scripts\python.exe -m pytest`
  - `.\.venv\Scripts\python.exe -m unittest`

## Python Path
- When a command needs imports from `src`, set `PYTHONPATH=src` for that command.

## Dependency Assumptions
- Project dependencies are expected to be installed in `.venv`.
- Do not fall back to the system Python unless the user explicitly asks for it.
