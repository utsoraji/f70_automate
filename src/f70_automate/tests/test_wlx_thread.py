import time
import unittest

from f70_automate.tests.mock.fake_wavelogger import (
    FakeMeasurementController,
    FakeWaveLoggerApp,
    FakeWaveLoggerDocument,
)
from f70_automate.domains.wavelogger.channel_config import ChannelConfig, TransformKind
from f70_automate.domains.wavelogger import WLXRuntime


def wait_for(predicate, timeout: float = 1.0, interval: float = 0.01) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return
        time.sleep(interval)
    raise TimeoutError("Condition was not met before timeout.")


def wait_until_awake(runtime: WLXRuntime) -> None:
    while (
        runtime.store.get_current_physical(runtime.store.default_channel) is None
        and runtime.runner.is_alive()
    ):
        time.sleep(0.1)
    runtime.store.check_exception()


class TestWLXRuntime(unittest.TestCase):
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
                },
                sample_interval_sec=0.01,
            )
        )
        runtime = WLXRuntime.create(
            filepath="fake_setup.xcf",
            app_factory=lambda: app,
            poll_interval=0.01,
            channels=(primary, secondary),
        )

        runtime.runner.start()
        wait_until_awake(runtime)
        wait_for(lambda: len(runtime.store.get_physical_history(primary)) >= 3)
        runtime.runner.stop()
        runtime.runner.join(timeout=1.0)

        self.assertEqual(runtime.store.get_current_voltage(primary), 0.2)
        self.assertAlmostEqual(runtime.store.get_current_physical(primary), 10.0**0.2)
        self.assertEqual(
            [round(value, 8) for value in runtime.store.get_physical_history(primary) if value is not None],
            [round(10.0**1.0, 8), round(10.0**0.8, 8), round(10.0**0.2, 8)],
        )
        self.assertEqual(runtime.store.get_current_physical(secondary), 60.0)
        self.assertEqual(runtime.store.get_physical_history(secondary), [40.0, 50.0, 60.0])
        self.assertEqual(app.connector.setup_calls, [0])
        self.assertEqual(app.measurement.loaded_paths, ["fake_setup.xcf"])
        self.assertTrue(app.measurement.started)
        self.assertTrue(app.measurement.stopped)
        self.assertTrue(app.entered)
        self.assertTrue(app.exited)
        self.assertEqual(runtime.channels, (primary, secondary))
        self.assertIs(runtime.store.default_channel, primary)

    def test_wlx_logger_surfaces_background_exception(self):
        app = FakeWaveLoggerApp(
            document=FakeWaveLoggerDocument(
                samples_by_channel={(1, 0): [1.0]},
                fail_on_current_call=1,
                sample_interval_sec=0.01,
            ),
        )
        runtime = WLXRuntime.create(
            filepath="fake_setup.xcf",
            app_factory=lambda: app,
            poll_interval=0.01,
        )

        runtime.runner.start()
        wait_for(lambda: runtime.store.exception is not None)
        runtime.runner.join(timeout=1.0)

        with self.assertRaisesRegex(RuntimeError, "Fake current data read failed."):
            _ = runtime.store.get_current_physical(runtime.store.default_channel)

    def test_wlx_logger_surfaces_start_failure(self):
        app = FakeWaveLoggerApp(
            document=FakeWaveLoggerDocument(
                samples_by_channel={(1, 0): [1.0]},
                sample_interval_sec=0.01,
            ),
            measurement=FakeMeasurementController(fail_on_start=True),
        )
        runtime = WLXRuntime.create(
            filepath="fake_setup.xcf",
            app_factory=lambda: app,
            poll_interval=0.01,
        )

        runtime.runner.start()
        wait_for(lambda: runtime.store.exception is not None)
        runtime.runner.join(timeout=1.0)

        with self.assertRaisesRegex(RuntimeError, "Fake measurement start failed."):
            _ = runtime.store.get_physical_history(runtime.store.default_channel)

    def test_wlx_logger_extends_samples_beyond_seed_data(self):
        primary = ChannelConfig("voltage_a", "Voltage A", 1, 0, scale=1.0, offset=0.0, unit="V")
        app = FakeWaveLoggerApp(
            document=FakeWaveLoggerDocument(
                samples_by_channel={(1, 0): [0.1, 0.2]},
                sample_interval_sec=0.01,
                random_step=0.01,
            )
        )
        runtime = WLXRuntime.create(
            filepath="fake_setup.xcf",
            app_factory=lambda: app,
            poll_interval=0.01,
            channels=(primary,),
        )

        runtime.runner.start()
        wait_until_awake(runtime)
        wait_for(lambda: len(runtime.store.get_physical_history(primary)) >= 5)
        runtime.runner.stop()
        runtime.runner.join(timeout=1.0)

        history = runtime.store.get_physical_history(primary)
        self.assertGreaterEqual(len(history), 5)

    def test_wlx_logger_emits_physical_sample_events(self):
        primary = ChannelConfig("voltage_a", "Voltage A", 1, 0, scale=1.0, offset=0.0, unit="V")
        secondary = ChannelConfig("voltage_b", "Voltage B", 1, 1, scale=10.0, offset=0.0, unit="K")
        app = FakeWaveLoggerApp(
            document=FakeWaveLoggerDocument(
                samples_by_channel={(1, 0): [0.1, 0.2, 0.3], (1, 1): [1.0, 2.0, 3.0]},
                sample_interval_sec=0.01,
            )
        )
        runtime = WLXRuntime.create(
            filepath="fake_setup.xcf",
            app_factory=lambda: app,
            poll_interval=0.01,
            channels=(primary, secondary),
        )
        received: list[tuple[float, tuple[tuple[str, float | None], ...]]] = []

        runtime.publisher.add_physical_listener(
            lambda batch: received.append(
                (
                    batch.received_at,
                    tuple((channel.key, value) for channel, value in batch.physical_values),
                )
            )
        )
        runtime.runner.start()
        wait_until_awake(runtime)
        wait_for(lambda: len(received) >= 3)
        runtime.runner.stop()
        runtime.runner.join(timeout=1.0)

        self.assertEqual(
            [values for _, values in received[:3]],
            [
                (("voltage_a", 0.1), ("voltage_b", 10.0)),
                (("voltage_a", 0.2), ("voltage_b", 20.0)),
                (("voltage_a", 0.3), ("voltage_b", 30.0)),
            ],
        )
        self.assertTrue(all(received_at > 0 for received_at, _ in received[:3]))

    def test_wlx_runtime_exposes_runner_store_and_publisher(self):
        primary = ChannelConfig("voltage_a", "Voltage A", 1, 0, scale=1.0, offset=0.0, unit="V")
        app = FakeWaveLoggerApp(
            document=FakeWaveLoggerDocument(
                samples_by_channel={(1, 0): [0.1, 0.2, 0.3]},
                sample_interval_sec=0.01,
            )
        )
        runtime = WLXRuntime.create(
            filepath="fake_setup.xcf",
            app_factory=lambda: app,
            poll_interval=0.01,
            channels=(primary,),
        )

        self.assertEqual(runtime.channels, (primary,))
        self.assertIsNotNone(runtime.store)
        self.assertIsNotNone(runtime.publisher)
        self.assertIsNotNone(runtime.runner)

    def test_wlx_logger_cannot_restart_after_stop(self):
        primary = ChannelConfig("voltage_a", "Voltage A", 1, 0, scale=1.0, offset=0.0, unit="V")
        app = FakeWaveLoggerApp(
            document=FakeWaveLoggerDocument(
                samples_by_channel={(1, 0): [0.1, 0.2, 0.3]},
                sample_interval_sec=0.01,
            )
        )
        runtime = WLXRuntime.create(
            filepath="fake_setup.xcf",
            app_factory=lambda: app,
            poll_interval=0.01,
            channels=(primary,),
        )

        runtime.runner.start()
        wait_until_awake(runtime)
        wait_for(lambda: len(runtime.store.get_physical_history(primary)) >= 2)
        runtime.runner.stop()
        runtime.runner.join(timeout=1.0)

        with self.assertRaisesRegex(RuntimeError, "cannot be started more than once"):
            runtime.runner.start()


if __name__ == "__main__":
    unittest.main()
