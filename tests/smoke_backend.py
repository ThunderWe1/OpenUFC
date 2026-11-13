"""Exercise frozen VISA and Telnet imports using local instrument simulators."""

import json
import os
from pathlib import Path
import socketserver
import subprocess
import sys
import tempfile
import threading
import urllib.request


class Instrument(socketserver.StreamRequestHandler):
    def handle(self):
        for command in self.rfile:
            if command.strip() == b"*IDN?":
                self.wfile.write(self.server.identity + b"\r\n")


def main():
    executable = Path(sys.argv[1]).resolve(strict=True)
    env = os.environ.copy()
    env["PATH"] = str(Path(os.environ["SystemRoot"]) / "System32")
    env["PYVISA_LIBRARY"] = "@py"
    env.pop("PYTHONPATH", None)
    env.pop("PYTHONHOME", None)
    with tempfile.TemporaryDirectory(prefix="openufc-backend-check-") as folder:
        with open(Path(folder) / "stderr.txt", "w+", encoding="utf-8") as errors:
            backend = subprocess.Popen(
                [str(executable), "--server", "--port", "0"], cwd=folder,
                env=env, stdout=subprocess.PIPE, stderr=errors, text=True,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
            watchdog = threading.Timer(45, backend.kill)
            watchdog.start()
            base = None
            try:
                line = backend.stdout.readline()
                assert line, "Frozen backend did not start"
                ready = json.loads(line)
                assert ready["event"] == "SERVER_READY"
                base = f"http://{ready['host']}:{ready['port']}"

                def request(route, payload=None):
                    data = None if payload is None else json.dumps(payload).encode()
                    req = urllib.request.Request(base + route, data=data, headers={"Content-Type": "application/json"})
                    with urllib.request.urlopen(req, timeout=10) as response:
                        return json.load(response)

                assert request("/api/health")["ok"]
                assert len(request("/api/config")["instruments"]) == 2
                for kind, identity in (
                    ("ufc", b"KEYSIGHT,53220A,SMOKE,1"),
                    ("dmm", b"KEYSIGHT,34461A,SMOKE,1"),
                    ("wlm", b"Bristol Instruments,771B-NIR,SMOKE,1"),
                ):
                    with socketserver.ThreadingTCPServer(("127.0.0.1", 0), Instrument) as instrument:
                        instrument.daemon_threads = True
                        instrument.identity = identity
                        threading.Thread(target=instrument.serve_forever, daemon=True).start()
                        port = instrument.server_address[1]
                        item = request("/api/instruments", {"type": kind})
                        payload = {"resource": f"TCPIP0::127.0.0.1::{port}::SOCKET"}
                        if kind == "wlm":
                            payload = {"connection_mode": "ethernet", "ethernet_resource": f"127.0.0.1:{port}"}
                        try:
                            result = request(f"/api/instruments/{item['id']}/check", payload)
                            assert result["connected"] and result["identity"] == identity.decode(), result
                        finally:
                            instrument.shutdown()
                request("/api/shutdown", {})
                assert backend.wait(timeout=10) == 0
                print("Frozen backend passed: config, health, PyVISA-py UFC/DMM, and Bristol Telnet.")
            finally:
                watchdog.cancel()
                if backend.poll() is None:
                    backend.kill()
                    backend.wait(timeout=10)
                errors.seek(0)
                diagnostics = errors.read()
                if backend.returncode:
                    print(diagnostics, file=sys.stderr)


if __name__ == "__main__":
    main()
