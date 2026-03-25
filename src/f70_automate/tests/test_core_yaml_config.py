from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import unittest

from f70_automate._core.config.yaml_config import (
    ConfigError,
    dump_yaml,
    load_yaml,
    parse_section,
    parse_section_list,
    read_yaml,
    write_yaml,
)


@dataclass(frozen=True)
class DemoConfig:
    key: str
    value: int

    @classmethod
    def from_dict(cls, data: dict[str, object]) -> "DemoConfig":
        return cls(
            key=str(data["key"]),
            value=int(data["value"]),
        )


class TestYamlConfigCore(unittest.TestCase):
    def test_parse_section_with_three_level_path(self) -> None:
        text = """
app:
  automation:
    settings:
      key: mode
      value: 3
"""
        payload = load_yaml(text)

        parsed = parse_section(payload, ("app", "automation", "settings"), DemoConfig.from_dict)

        self.assertEqual(parsed, DemoConfig(key="mode", value=3))

    def test_parse_section_list_with_three_level_path(self) -> None:
        text = """
app:
  wavelogger:
    channels:
      - key: ch1
        value: 10
      - key: ch2
        value: 20
"""
        payload = load_yaml(text)

        parsed = parse_section_list(payload, ("app", "wavelogger", "channels"), DemoConfig.from_dict)

        self.assertEqual(
            parsed,
            (
                DemoConfig(key="ch1", value=10),
                DemoConfig(key="ch2", value=20),
            ),
        )

    def test_round_trip_file_io(self) -> None:
        payload = {
            "app": {
                "serial": {
                    "port": "COM3",
                    "baudrate": 9600,
                }
            }
        }

        path = Path("src/f70_automate/tests/app_config_test.yaml")
        try:
            write_yaml(path, payload)
            loaded = read_yaml(path)
        finally:
            if path.exists():
                path.unlink()

        self.assertEqual(loaded, payload)
        self.assertIn("serial", dump_yaml(payload))

    def test_missing_path_raises_config_error(self) -> None:
        payload = {"app": {"automation": {}}}

        with self.assertRaises(ConfigError):
            parse_section(payload, ("app", "automation", "settings"), DemoConfig.from_dict)

    def test_wrong_section_shape_raises_config_error(self) -> None:
        payload = {
            "app": {
                "wavelogger": {
                    "channels": {
                        "key": "not-a-list"
                    }
                }
            }
        }

        with self.assertRaises(ConfigError):
            parse_section_list(payload, ("app", "wavelogger", "channels"), DemoConfig.from_dict)


if __name__ == "__main__":
    unittest.main()
