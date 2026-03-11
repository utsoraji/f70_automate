"""
Base class for thread-based runners.

This module provides a generic framework for managing background threads
with proper lifecycle management (start, stop, join, is_alive).
"""

from __future__ import annotations

import threading
from abc import ABC, abstractmethod


class ThreadRunner(ABC):
    """
    Abstract base class for background thread runners.

    Provides common thread lifecycle management:
    - start() / stop() / join() / is_alive()
    - Thread-safe state management
    - Proper cleanup semantics

    Subclasses must implement _run_loop() to define thread behavior.
    """

    def __init__(self) -> None:
        """Initialize the thread runner."""
        self._stop_event = threading.Event()
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._lock = threading.Lock()
        self._started = False

    @abstractmethod
    def _run_loop(self) -> None:
        """
        Run the thread loop.

        Subclasses must implement this method. It should check
        self._stop_event.is_set() or use is_stop_requested() to
        determine when to exit.

        Example:
            while not self.is_stop_requested():
                # do work
                pass
        """

    def start(self) -> None:
        """
        Start the background thread.

        Raises:
            RuntimeError: If the runner has already been started.
        """
        with self._lock:
            if self._started:
                raise RuntimeError(
                    "This runner cannot be started more than once."
                )
            self._started = True
            self._stop_event.clear()
            thread = self._thread
        thread.start()

    def stop(self) -> None:
        """Request the background thread to stop."""
        self._stop_event.set()

    def is_stop_requested(self) -> bool:
        """Check if a stop request has been made."""
        return self._stop_event.is_set()

    def join(self, timeout: float | None = None) -> None:
        """
        Wait for the background thread to finish.

        Args:
            timeout: Maximum time to wait in seconds. None means wait forever.
        """
        self._thread.join(timeout=timeout)

    def is_alive(self) -> bool:
        """Check if the background thread is currently running."""
        with self._lock:
            return self._thread.is_alive()

    @property
    def daemon(self) -> bool:
        """Get the daemon property of the background thread."""
        with self._lock:
            return self._thread.daemon

    @daemon.setter
    def daemon(self, value: bool) -> None:
        """
        Set the daemon property of the background thread.

        Can only be set before the thread is started.

        Raises:
            RuntimeError: If the thread is already running.
        """
        with self._lock:
            if self._thread.is_alive():
                raise RuntimeError(
                    "Cannot change daemon while thread is running."
                )
            self._thread.daemon = value
