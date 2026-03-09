import time
import unittest

from f70_automate.test.mock.fake_wavelogger import (
    FakeMeasurementController,
    FakeWaveLoggerApp,
    FakeWaveLoggerDocument,
)
from f70_automate.wavelogger.channel_config import ChannelConfig, TransformKind
from f70_automate.wavelogger.wlx_thread import WLXDataLogger


def wait_for(predicate, timeout: float = 1.0, interval: float = 0.01) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return
        time.sleep(interval)
    raise TimeoutError("Condition was not met before timeout.")


class TestWLXDataLogger(unittest.TestCase):
    def test_wlx_logger_collects_current_data_and_history(self):
        primary = ChannelConfig(
            "voltage_a",
            "Voltage A",
            1,
            0,
            transform=TransformKind.LOG10_EXP,
            scale=1.0,
            offset=0.0,
            unit="arb",
        )
        secondary = ChannelConfig("voltage_b", "Voltage B", 1, 1, scale=100.0, offset=-10.0, unit="K")
        app = FakeWaveLoggerApp(
            document=FakeWaveLoggerDocument(
                samples_by_channel={
                    (1, 0): [1.0, 0.8, 0.2],
                    (1, 1): [0.5, 0.6, 0.7],
                }
            )
        )
        logger = WLXDataLogger(
            filepath="fake_setup.xcf",
            app_factory=lambda: app,
            poll_interval=0.01,
            channels=(primary, secondary),
        )

        logger.start()
        logger.wait_until_awake()
        wait_for(lambda: len(logger.get_physical_history(primary)) == 3)
        logger.stop()
        logger.join(timeout=1.0)

        self.assertEqual(logger.get_current_voltage(primary), 0.2)
        self.assertAlmostEqual(logger.get_current_physical(primary), 10.0**0.2)
        self.assertEqual(
            [round(value, 8) for value in logger.get_physical_history(primary)],
            [round(10.0**1.0, 8), round(10.0**0.8, 8), round(10.0**0.2, 8)],
        )
        self.assertEqual(logger.get_current_physical(secondary), 60.0)
        self.assertEqual(logger.get_physical_history(secondary), [40.0, 50.0, 60.0])
        self.assertEqual(app.connector.setup_calls, [0])
        self.assertEqual(app.measurement.loaded_paths, ["fake_setup.xcf"])
        self.assertTrue(app.measurement.started)
        self.assertTrue(app.measurement.stopped)
        self.assertTrue(app.entered)
        self.assertTrue(app.exited)

    def test_wlx_logger_surfaces_background_exception(self):
        app = FakeWaveLoggerApp(
            document=FakeWaveLoggerDocument(samples_by_channel={(1, 0): [1.0]}, fail_on_current_call=1),
        )
        logger = WLXDataLogger(
            filepath="fake_setup.xcf",
            app_factory=lambda: app,
            poll_interval=0.01,
        )

        logger.start()
        wait_for(lambda: logger._exception is not None)
        logger.join(timeout=1.0)

        with self.assertRaisesRegex(RuntimeError, "Fake current data read failed."):
            _ = logger.current_data

    def test_wlx_logger_surfaces_start_failure(self):
        app = FakeWaveLoggerApp(
            document=FakeWaveLoggerDocument(samples_by_channel={(1, 0): [1.0]}),
            measurement=FakeMeasurementController(fail_on_start=True),
        )
        logger = WLXDataLogger(
            filepath="fake_setup.xcf",
            app_factory=lambda: app,
            poll_interval=0.01,
        )

        logger.start()
        wait_for(lambda: logger._exception is not None)
        logger.join(timeout=1.0)

        with self.assertRaisesRegex(RuntimeError, "Fake measurement start failed."):
            _ = logger.data


if __name__ == "__main__":
    unittest.main()
