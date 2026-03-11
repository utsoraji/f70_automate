from pathlib import Path
import unittest

from f70_automate.domains.wavelogger.channel_config import (
    ChannelConfig,
    TransformKind,
    dump_channel_configs,
    load_channel_configs,
    read_channel_configs,
    save_channel_configs,
)


class TestChannelConfigSerialization(unittest.TestCase):
    def test_round_trip_yaml_string(self):
        configs = (
            ChannelConfig(
                key="pressure",
                label="Pressure",
                unit_id=1,
                channel_id=0,
                transform=TransformKind.LOG10_EXP,
                scale=1.667,
                offset=-9.333,
                unit="Pa",
            ),
            ChannelConfig(
                key="temperature",
                label="Temperature",
                unit_id=1,
                channel_id=1,
                scale=25.0,
                offset=273.15,
                unit="K",
            ),
        )

        text = dump_channel_configs(configs)
        loaded = load_channel_configs(text)

        self.assertEqual(loaded, configs)
        self.assertIn("transform: log10_exp", text)
        self.assertIn("transform: linear", text)

    def test_round_trip_yaml_file(self):
        configs = (
            ChannelConfig(
                key="flow",
                label="Flow",
                unit_id=1,
                channel_id=2,
                scale=10.0,
                offset=0.0,
                unit="L/min",
            ),
        )

        path = Path("src/f70_automate/tests/channels_test.yaml")
        try:
            save_channel_configs(path, configs)
            loaded = read_channel_configs(path)
        finally:
            if path.exists():
                path.unlink()

        self.assertEqual(loaded, configs)


if __name__ == "__main__":
    unittest.main()
