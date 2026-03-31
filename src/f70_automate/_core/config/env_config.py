from __future__ import annotations

from pathlib import Path


def load_dotenv_file(path: Path | str = ".env", *, override: bool = False) -> bool:
    """Load environment variables from dotenv file when available.

    Returns True only when the file exists and was loaded.
    """
    env_path = Path(path)
    if not env_path.exists():
        return False

    try:
        from dotenv import load_dotenv
    except Exception:
        return False

    load_dotenv(dotenv_path=env_path, override=override)
    return True
