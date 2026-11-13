from __future__ import annotations

import json
import queue
import threading
import time
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

from laser_platform.config import ConfigStore
from laser_platform.instruments import InstrumentManager
from laser_platform.library import (
    delete_library_item,
    export_library_series,
    library_item_preview,
    library_frequency_noise,
    library_waveform_preview,
    list_library_files,
    rename_library_item,
)


class BackendHTTPServer(ThreadingHTTPServer):
    def __init__(
        self,
        server_address: tuple[str, int],
        instrument_manager: InstrumentManager,
        config_store: ConfigStore,
    ) -> None:
        super().__init__(server_address, BackendRequestHandler)
        self.instrument_manager = instrument_manager
        self.config_store = config_store


class BackendRequestHandler(BaseHTTPRequestHandler):
    server: BackendHTTPServer

    def log_message(self, format: str, *args: Any) -> None:
        return

    def do_OPTIONS(self) -> None:
        self.send_response(HTTPStatus.NO_CONTENT)
        self._send_cors_headers()
        self.end_headers()

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        path = parsed.path
        if path == "/api/devices":
            try:
                self._send_json(self.server.instrument_manager.devices_payload())
            except Exception as exc:
                self._send_json({"error": str(exc)}, HTTPStatus.SERVICE_UNAVAILABLE)
            return
        if path == "/api/instruments":
            self._send_json(self.server.instrument_manager.instruments_payload())
            return
        if path == "/api/instruments/events":
            self._send_instrument_events()
            return
        if path.startswith("/api/instruments/"):
            parts = path.strip("/").split("/")
            if len(parts) == 4 and parts[0] == "api" and parts[1] == "instruments":
                instance_id, action = parts[2], parts[3]
                if action == "resources":
                    self._send_json(self.server.instrument_manager.list_resources(instance_id))
                    return
                if action == "options":
                    self._send_json(self.server.instrument_manager.options(instance_id))
                    return
        if path == "/api/health":
            self._send_json({"ok": True})
            return
        if path == "/api/config":
            self._send_json(self.server.config_store.load())
            return
        if path == "/api/library":
            try:
                self._send_json(self._library_list())
            except Exception as exc:
                self._send_json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)
            return
        if path == "/api/library/item":
            try:
                query = parse_qs(parsed.query)
                file_name = query.get("file", [""])[0]
                self._send_json(library_item_preview(self._library_dir(), file_name))
            except Exception as exc:
                self._send_json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)
            return
        if path == "/api/library/waveform":
            try:
                query = parse_qs(parsed.query)
                file_name = query.get("file", [""])[0]
                self._send_json(library_waveform_preview(self._library_dir(), file_name))
            except Exception as exc:
                self._send_json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)
            return
        if path == "/api/library/frequency-noise":
            try:
                query = parse_qs(parsed.query)
                self._send_json(library_frequency_noise(
                    self._library_dir(), query.get("file", [""])[0],
                    segment_length=int(query.get("segment_length", ["1024"])[0]),
                    window=query.get("window", ["hann"])[0],
                    overlap_percent=int(query.get("overlap_percent", ["50"])[0]),
                ))
            except Exception as exc:
                self._send_json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)
            return
        self._send_json({"error": "not found"}, HTTPStatus.NOT_FOUND)

    def do_POST(self) -> None:
        path = urlparse(self.path).path
        try:
            payload = self._read_json()
            if path == "/api/instruments":
                self._send_json(self.server.instrument_manager.add_instrument(str(payload.get("type", ""))))
                return
            if path.startswith("/api/instruments/"):
                parts = path.strip("/").split("/")
                if len(parts) == 4 and parts[0] == "api" and parts[1] == "instruments":
                    instance_id, action = parts[2], parts[3]
                    if action == "rename":
                        self._send_json(self.server.instrument_manager.rename_instrument(instance_id, str(payload.get("display_name", ""))))
                        return
                    if action == "settings":
                        self._send_json(self.server.instrument_manager.update_settings(instance_id, payload))
                        return
                    if action == "check":
                        self._send_json(self.server.instrument_manager.check_connection(instance_id, payload))
                        return
                    if action == "start":
                        self._send_json(self.server.instrument_manager.start(instance_id, payload))
                        return
                    if action == "stop":
                        self._send_json(self.server.instrument_manager.stop(instance_id))
                        return
            if path == "/api/config":
                self._send_json(self.server.config_store.update(payload))
                return
            if path == "/api/library/rename":
                self._send_json(rename_library_item(self._library_dir(), str(payload.get("file", "")), str(payload.get("display_name", ""))))
                return
            if path == "/api/library/delete":
                self._send_json(delete_library_item(self._library_dir(), str(payload.get("file", "")), self._active_library_files()))
                return
            if path == "/api/library/export":
                self._send_json(
                    export_library_series(
                        self._library_dir(),
                        str(payload.get("file", "")),
                        str(payload.get("series", "")),
                        Path(str(payload.get("csv_path", ""))),
                    )
                )
                return
            if path == "/api/shutdown":
                self._send_json({"ok": True})
                threading.Thread(target=self._shutdown_soon, daemon=True).start()
                return
            self._send_json({"error": "not found"}, HTTPStatus.NOT_FOUND)
        except Exception as exc:
            self._send_json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)

    def do_DELETE(self) -> None:
        path = urlparse(self.path).path
        try:
            if path.startswith("/api/instruments/"):
                parts = path.strip("/").split("/")
                if len(parts) == 3 and parts[0] == "api" and parts[1] == "instruments":
                    self._send_json(self.server.instrument_manager.delete_instrument(parts[2]))
                    return
            self._send_json({"error": "not found"}, HTTPStatus.NOT_FOUND)
        except Exception as exc:
            self._send_json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)

    def _read_json(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length", "0"))
        if length <= 0:
            return {}
        raw = self.rfile.read(length)
        if not raw:
            return {}
        return json.loads(raw.decode("utf-8"))

    def _send_json(self, payload: dict[str, Any], status: HTTPStatus = HTTPStatus.OK) -> None:
        raw = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self._send_cors_headers()
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def _send_instrument_events(self) -> None:
        subscriber = self.server.instrument_manager.subscribe()
        self.send_response(HTTPStatus.OK)
        self._send_cors_headers()
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "keep-alive")
        self.end_headers()
        try:
            self._write_sse("status", {"text": "Instrument event stream connected"})
            while True:
                try:
                    item = subscriber.get(timeout=15.0)
                    self._write_sse(item["event"], item["data"])
                except queue.Empty:
                    self.wfile.write(b": keepalive\n\n")
                    self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            pass
        finally:
            self.server.instrument_manager.unsubscribe(subscriber)

    def _write_sse(self, event: str, data: dict[str, Any]) -> None:
        payload = f"event: {event}\ndata: {json.dumps(data)}\n\n".encode("utf-8")
        self.wfile.write(payload)
        self.wfile.flush()

    def _send_cors_headers(self) -> None:
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, DELETE, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")

    def _library_dir(self) -> Path:
        return Path(str(self.server.config_store.load()["platform"]["library_dir"])).expanduser()

    def _active_library_files(self) -> tuple[Path, ...]:
        return self.server.instrument_manager.active_library_files()

    def _library_list(self) -> dict[str, Any]:
        return list_library_files(self._library_dir(), self._active_library_files())

    def _shutdown_soon(self) -> None:
        time.sleep(0.1)
        self.server.instrument_manager.shutdown()
        self.server.shutdown()


def create_server(host: str = "127.0.0.1", port: int = 0, config_path: str | Path | None = None) -> BackendHTTPServer:
    config_store = ConfigStore(Path(config_path) if config_path is not None else None)
    instrument_manager = InstrumentManager(config_store)
    return BackendHTTPServer((host, int(port)), instrument_manager, config_store)


def run_server(host: str = "127.0.0.1", port: int = 0, announce: bool = True) -> None:
    server = create_server(host, port)
    actual_host, actual_port = server.server_address
    if announce:
        print(json.dumps({"event": "SERVER_READY", "host": actual_host, "port": actual_port}), flush=True)
    try:
        server.serve_forever()
    finally:
        server.instrument_manager.shutdown()
        server.server_close()
