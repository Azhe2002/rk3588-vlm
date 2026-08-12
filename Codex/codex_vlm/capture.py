from __future__ import annotations

import json
import os
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence

from .schema import sha256_bytes
from .storage import atomic_write_json


def capture_frames(
    *,
    output: Path,
    dataset_id: str,
    count: int,
    command: Sequence[str],
    interval_s: float,
    ground_truth: str | None,
    source_session_id: str,
    width: int | None,
    height: int | None,
) -> Path:
    """Run one Linux capture command per frame and freeze exact JPEG bytes."""
    if count < 1:
        raise ValueError("count must be positive")
    if interval_s < 0:
        raise ValueError("interval cannot be negative")
    if ground_truth not in (None, "yes", "no"):
        raise ValueError("ground_truth must be yes, no, or omitted")
    if not command or not any("{output}" in arg for arg in command):
        raise ValueError("capture command must contain an argv item with {output}")

    output = output.resolve()
    if output.exists():
        raise FileExistsError(f"capture output already exists: {output}")
    frames_dir = output / "frames"
    frames_dir.mkdir(parents=True)
    log_path = output / "capture.log"
    manifest_path = output / "dataset.json"
    frames: list[dict[str, Any]] = []
    started_at = _utc_now()
    status = "running"
    error: str | None = None
    _write_manifest(
        manifest_path, dataset_id, source_session_id, started_at, None,
        status, error, command, frames,
    )

    try:
        with log_path.open("ab", buffering=0) as log:
            for sequence in range(1, count + 1):
                captured_at = _utc_now()
                captured_monotonic_ms = time.monotonic_ns() // 1_000_000
                temporary = frames_dir / f".capture_{sequence:04d}_{os.getpid()}.jpg"
                argv = [
                    arg.replace("{output}", str(temporary)).replace("{index}", str(sequence))
                    for arg in command
                ]
                log.write(f"\n[{captured_at}] argv={json.dumps(argv)}\n".encode("utf-8"))
                result = subprocess.run(
                    argv,
                    stdin=subprocess.DEVNULL,
                    stdout=log,
                    stderr=subprocess.STDOUT,
                    check=False,
                )
                if result.returncode != 0:
                    raise RuntimeError(f"capture command exited with code {result.returncode}")
                if not temporary.is_file() or temporary.stat().st_size == 0:
                    raise RuntimeError("capture command did not create a non-empty JPEG")

                data = temporary.read_bytes()
                digest = sha256_bytes(data)
                frame_id = f"f{sequence:04d}_{digest[:12]}"
                final_path = frames_dir / f"{frame_id}.jpg"
                os.replace(temporary, final_path)
                frames.append(
                    {
                        "frame_id": frame_id,
                        "path": final_path.relative_to(output).as_posix(),
                        "ground_truth": ground_truth,
                        "source_session_id": source_session_id,
                        "source_width": width,
                        "source_height": height,
                        "sha256": digest,
                        "bytes": len(data),
                        "metadata": {
                            "capture_sequence": sequence,
                            "captured_at_utc": captured_at,
                            "captured_monotonic_ms": captured_monotonic_ms,
                        },
                    }
                )
                _write_manifest(
                    manifest_path, dataset_id, source_session_id, started_at, None,
                    status, error, command, frames,
                )
                if sequence < count and interval_s:
                    time.sleep(interval_s)
        status = "complete"
    except BaseException as exc:
        status = "failed"
        error = f"{type(exc).__name__}: {exc}"
        raise
    finally:
        _write_manifest(
            manifest_path, dataset_id, source_session_id, started_at, _utc_now(),
            status, error, command, frames,
        )
    return manifest_path


def _write_manifest(
    path: Path,
    dataset_id: str,
    source_session_id: str,
    started_at: str,
    finished_at: str | None,
    status: str,
    error: str | None,
    command: Sequence[str],
    frames: list[dict[str, Any]],
) -> None:
    atomic_write_json(
        path,
        {
            "schema_version": 1,
            "dataset_id": dataset_id,
            "source_session_id": source_session_id,
            "started_at_utc": started_at,
            "finished_at_utc": finished_at,
            "status": status,
            "error": error,
            "capture_command": list(command),
            "frames": frames,
        },
    )


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")
