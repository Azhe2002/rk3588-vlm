from __future__ import annotations

import os
import subprocess
import time
from pathlib import Path
from typing import IO, Any

from .config import ServerConfig
from .request_client import LlamaHttpClient
from .linux_server import start_process, stop_process


class ServerLifecycle:
    def __init__(self, config: ServerConfig, log_path: Path) -> None:
        self.config = config
        self.log_path = log_path
        self.client = LlamaHttpClient(config.url, timeout_s=config.request_timeout_s)
        self.process: subprocess.Popen[bytes] | None = None
        self._log: IO[bytes] | None = None

    def __enter__(self) -> "ServerLifecycle":
        if self.config.mode == "managed":
            healthy, _ = self.client.health()
            if healthy:
                raise RuntimeError(
                    "managed mode refused to start because the configured endpoint is already healthy; "
                    "stop the existing server or use external mode"
                )
            self.log_path.parent.mkdir(parents=True, exist_ok=True)
            self._log = self.log_path.open("ab", buffering=0)
            self._log.write(b"\n=== managed server start ===\n")
            self.process = start_process(self.config.command, self._log)
        self._wait_until_ready()
        return self

    def _wait_until_ready(self) -> None:
        deadline = time.monotonic() + self.config.startup_timeout_s
        last_message = "not checked"
        while time.monotonic() < deadline:
            if self.process is not None and self.process.poll() is not None:
                raise RuntimeError(
                    f"managed llama-server exited before health check (code {self.process.returncode}); "
                    f"see {self.log_path}"
                )
            healthy, last_message = self.client.health()
            if healthy:
                return
            time.sleep(1.0)
        raise TimeoutError(
            f"llama-server was not ready after {self.config.startup_timeout_s}s: {last_message}"
        )

    def manifest_fields(self) -> dict[str, Any]:
        return {
            "server_mode": self.config.mode,
            "server_url": self.config.url,
            "server_command": list(self.config.command),
            "server_pid": self.process.pid if self.process is not None else None,
            "server_owner_pid": os.getpid() if self.process is not None else None,
        }

    def __exit__(self, exc_type: Any, exc: Any, traceback: Any) -> None:
        if self.process is not None:
            if os.name == "posix":
                os.killpg(self.process.pid, 15)
            else:
                self.process.terminate()
            try:
                self.process.wait(timeout=15)
            except subprocess.TimeoutExpired:
                if os.name == "posix":
                    os.killpg(self.process.pid, 9)
                else:
                    self.process.kill()
                self.process.wait(timeout=5)
        if self._log is not None:
            self._log.write(b"=== managed server stop ===\n")
            self._log.close()
            self._log = None
