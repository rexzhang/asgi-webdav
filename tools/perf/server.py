"""The asgi-webdav server-under-test subprocess management."""

from __future__ import annotations

import http.client
import socket
import subprocess
import time
from pathlib import Path

from tools.common.env import REPO_ROOT
from tools.perf.interpreters import Interpreter
from tools.perf.settings import scrub_child_env

READY_TIMEOUT = 30.0
BASIC_AUTH_VALUE = "Basic dXNlcm5hbWU6cGFzc3dvcmQ="  # username:password


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def parse_cputime(text: str) -> float:
    """Parse ps cputime output like '0:03.41' or '1:02:03.40'."""
    seconds = 0.0
    for part in text.strip().split(":"):
        try:
            seconds = seconds * 60.0 + float(part)
        except ValueError:
            return 0.0
    return seconds


def _probe_ready(port: int) -> bool:
    response: http.client.HTTPResponse | None = None
    try:
        conn = http.client.HTTPConnection("127.0.0.1", port, timeout=1.5)
        conn.request("OPTIONS", "/", headers={"Authorization": BASIC_AUTH_VALUE})
        response = conn.getresponse()
        response.read()
        conn.close()
    except OSError:
        return False
    return response is not None and 100 <= response.status < 600


class ServerHandle:
    """The asgi-webdav server under test (uvicorn subprocess)."""

    def __init__(
        self,
        interp: Interpreter,
        config_path: Path,
        log_path: Path,
        *,
        env_extra: dict[str, str] | None = None,
    ) -> None:
        self.port = _free_port()
        self.log_path = log_path
        self.cpu_start = 0.0
        env = scrub_child_env()
        env.update(interp.env_extra)
        if env_extra:
            env.update(env_extra)
        argv = [
            str(interp.path),
            "-m",
            "asgi_webdav",
            "-c",
            str(config_path),
            "-H",
            "127.0.0.1",
            "-P",
            str(self.port),
        ]
        log_file = log_path.open("w", encoding="utf-8")
        self.process = subprocess.Popen(
            argv,
            cwd=str(REPO_ROOT),
            env=env,
            stdout=log_file,
            stderr=subprocess.STDOUT,
        )
        log_file.close()

    def wait_ready(self, timeout: float = READY_TIMEOUT) -> bool:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self.process.poll() is not None:
                return False
            if _probe_ready(self.port):
                self.cpu_start = self._read_cpu()
                return True
            time.sleep(0.15)
        return False

    def cpu_seconds(self) -> float:
        return max(0.0, self._read_cpu() - self.cpu_start)

    def _read_cpu(self) -> float:
        try:
            result = subprocess.run(
                ["ps", "-o", "cputime=", "-p", str(self.process.pid)],
                timeout=10,
                text=True,
                capture_output=True,
            )
        except (OSError, subprocess.TimeoutExpired):
            return 0.0
        return parse_cputime(result.stdout)

    def stop(self) -> None:
        if self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=10)
