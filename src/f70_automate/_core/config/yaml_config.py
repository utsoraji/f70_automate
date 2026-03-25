from __future__ import annotations

from pathlib import Path
from typing import Any, Callable, TypeVar

import yaml

ConfigPath = tuple[str, ...]
T = TypeVar("T")


class ConfigError(ValueError):
    """Raised when a YAML config path or shape is invalid."""


def _render_path(path: ConfigPath) -> str:
    return ".".join(path)


def _require_valid_path(path: ConfigPath) -> None:
    if not path:
        raise ConfigError("Config path must not be empty")
    if any(not key for key in path):
        raise ConfigError("Config path must not contain empty keys")


def load_yaml(text: str) -> dict[str, Any]:
    """Load YAML text into a dictionary payload."""
    payload = yaml.safe_load(text)
    if payload is None:
        return {}
    if not isinstance(payload, dict):
        raise ConfigError("Top-level YAML payload must be a mapping")
    return payload


def read_yaml(path: Path | str) -> dict[str, Any]:
    """Read a YAML file from disk and return a mapping payload."""
    return load_yaml(Path(path).read_text(encoding="utf-8"))


def dump_yaml(payload: dict[str, Any]) -> str:
    """Dump mapping payload to YAML text."""
    return yaml.safe_dump(payload, sort_keys=False, allow_unicode=True)


def write_yaml(path: Path | str, payload: dict[str, Any]) -> None:
    """Write mapping payload to YAML file."""
    Path(path).write_text(dump_yaml(payload), encoding="utf-8")


def get_node(payload: dict[str, Any], path: ConfigPath) -> Any:
    """Traverse nested mappings by path and return the target node."""
    _require_valid_path(path)

    current: Any = payload
    walked: list[str] = []
    for key in path:
        walked.append(key)
        if not isinstance(current, dict):
            raise ConfigError(
                f"Config path '{_render_path(tuple(walked))}' is not a mapping"
            )
        if key not in current:
            raise ConfigError(f"Missing config path: {_render_path(path)}")
        current = current[key]

    return current


def parse_section(
    payload: dict[str, Any],
    path: ConfigPath,
    factory: Callable[[dict[str, Any]], T],
) -> T:
    """Parse one mapping section into a typed config object."""
    node = get_node(payload, path)
    if not isinstance(node, dict):
        raise ConfigError(f"Config path '{_render_path(path)}' must be a mapping")
    return factory(node)


def parse_section_list(
    payload: dict[str, Any],
    path: ConfigPath,
    item_factory: Callable[[dict[str, Any]], T],
) -> tuple[T, ...]:
    """Parse one list section into typed config objects."""
    node = get_node(payload, path)
    if not isinstance(node, list):
        raise ConfigError(f"Config path '{_render_path(path)}' must be a list")

    parsed_items: list[T] = []
    for index, item in enumerate(node):
        if not isinstance(item, dict):
            raise ConfigError(
                f"Config path '{_render_path(path)}[{index}]' must be a mapping"
            )
        parsed_items.append(item_factory(item))
    return tuple(parsed_items)
