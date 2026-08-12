from __future__ import annotations

import os
import signal
import subprocess
from typing import IO


def start_process(command: tuple[str, ...], log: IO[bytes]) -> subprocess.Popen[bytes]:
    """Start llama-server as an isolated Linux process group."""
    return subprocess.Popen(
        list(command),
        stdin=subprocess.DEVNULL,
        stdout=log,
        stderr=subprocess.STDOUT,
        start_new_session=True,
    )


def stop_process(process: subprocess.Popen[bytes] | None) -> None:
    """Stop only the managed process group; never use pkill or a global name match."""
    if process is None or process.poll() is not None:
        return
    os.killpg(process.pid, signal.SIGTERM)
    try:
        process.wait(timeout=15)
    except subprocess.TimeoutExpired:
        os.killpg(process.pid, signal.SIGKILL)
        process.wait(timeout=5)
