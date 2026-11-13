from __future__ import annotations

import queue
import threading
from pathlib import Path
from typing import Any, Callable


class AcquisitionController:
    def __init__(
        self,
        event_from_message: Callable[[object], dict[str, Any] | None],
        terminal_messages: tuple[type, ...],
        thread_name: str,
        on_event: Callable[[str, dict[str, Any]], None],
    ) -> None:
        self.messages: queue.Queue[object] = queue.Queue()
        self._worker: Any = None
        self._lock = threading.Lock()
        self.publish = on_event
        self._event_from_message = event_from_message
        self._terminal_messages = terminal_messages
        self._dispatcher_stop = threading.Event()
        self._dispatcher = threading.Thread(target=self._dispatch_messages, name=thread_name, daemon=True)
        self._dispatcher.start()

    def is_running(self) -> bool:
        with self._lock:
            return self._worker is not None

    def active_library_file(self) -> Path | None:
        with self._lock:
            worker = self._worker
        return worker.library_file if worker is not None else None

    def _dispatch_messages(self) -> None:
        while not self._dispatcher_stop.is_set():
            try:
                message = self.messages.get(timeout=0.25)
            except queue.Empty:
                continue
            event = self._event_from_message(message)
            if event is None:
                continue
            if isinstance(message, self._terminal_messages):
                with self._lock:
                    self._worker = None
            self.publish(event["event"], event["data"])
