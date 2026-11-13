"""Check the single EXE outside the checkout without Python/Node on PATH."""

import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile


def main() -> None:
    executable = Path(sys.argv[1]).resolve(strict=True)
    env = os.environ.copy()
    windows = Path(os.environ["SystemRoot"])
    env["PATH"] = os.pathsep.join(map(str, (
        windows, windows / "System32", windows / "System32/WindowsPowerShell/v1.0",
    )))
    for key in ("ELECTRON_RUN_AS_NODE", "PYTHONPATH", "PYTHONHOME"):
        env.pop(key, None)
    env["OPENUFC_PYTHON"] = str(executable.parent / "python-must-not-be-used.exe")
    with tempfile.TemporaryDirectory(prefix="openufc-portable-check-") as folder:
        copied = Path(folder) / executable.name
        shutil.copy2(executable, copied)
        assert list(Path(folder).iterdir()) == [copied]
        result = subprocess.run(
            [str(copied), "--smoke"], cwd=folder, env=env,
            timeout=240, creationflags=subprocess.CREATE_NO_WINDOW,
        )
        if result.returncode:
            error_log = Path(tempfile.gettempdir()) / "openufc-smoke-error.txt"
            if error_log.exists():
                print(error_log.read_text(encoding="utf-8"), file=sys.stderr)
            raise SystemExit(result.returncode)
    print("Portable EXE passed: single file, separate folder, no Python/Node on PATH.")


if __name__ == "__main__":
    main()
