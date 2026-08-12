from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping

from .schema import canonical_json


@dataclass(frozen=True)
class RunPaths:
    root: Path
    session_manifest: Path
    manifest: Path
    plan: Path
    rounds: Path
    server_log: Path
    checksums: Path
    lock: Path


class RunStore:
    def __init__(self, output_root: Path, session_id: str, run_id: str, resume: bool) -> None:
        self.paths = _paths(output_root.resolve(), session_id, run_id)
        self.resume = resume
        self._lock_fd: int | None = None

    def __enter__(self) -> "RunStore":
        root = self.paths.root
        if root.exists() and not self.resume:
            raise FileExistsError(
                f"run directory already exists: {root}; use --resume to continue it"
            )
        if self.resume and not root.is_dir():
            raise FileNotFoundError(f"cannot resume missing run directory: {root}")
        root.mkdir(parents=True, exist_ok=self.resume)
        try:
            self._lock_fd = os.open(self.paths.lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.write(self._lock_fd, f"pid={os.getpid()}\n".encode("ascii"))
            os.fsync(self._lock_fd)
        except FileExistsError as exc:
            raise RuntimeError(f"run is locked by another process: {self.paths.lock}") from exc
        return self

    def __exit__(self, exc_type: Any, exc: Any, traceback: Any) -> None:
        if self._lock_fd is not None:
            os.close(self._lock_fd)
            self._lock_fd = None
        try:
            self.paths.lock.unlink()
        except FileNotFoundError:
            pass

    def initialize(
        self,
        *,
        session_manifest: Mapping[str, Any],
        manifest: Mapping[str, Any],
        plan: Iterable[Mapping[str, Any]],
    ) -> None:
        session_path = self.paths.session_manifest
        if not session_path.exists():
            atomic_write_json(session_path, session_manifest)
        else:
            current_session = json.loads(session_path.read_text(encoding="utf-8"))
            if current_session.get("session_id") != session_manifest.get("session_id"):
                raise RuntimeError(f"session manifest identity mismatch: {session_path}")

        if self.resume:
            self._verify_identity(manifest)
            if not self.paths.plan.is_file() or not self.paths.manifest.is_file():
                raise RuntimeError("resume directory is missing manifest.json or plan.jsonl")
            return

        atomic_write_json(self.paths.manifest, manifest)
        atomic_write_jsonl(self.paths.plan, plan)
        self.paths.rounds.touch(exist_ok=False)

    def _verify_identity(self, expected: Mapping[str, Any]) -> None:
        if not self.paths.manifest.is_file():
            return
        current = json.loads(self.paths.manifest.read_text(encoding="utf-8"))
        keys = (
            "schema_version",
            "session_id",
            "run_id",
            "experiment_id",
            "config_sha256",
            "experiment_fingerprint",
            "plan_sha256",
        )
        differences = [key for key in keys if current.get(key) != expected.get(key)]
        if differences:
            raise RuntimeError(
                "resume configuration does not match existing run: " + ", ".join(differences)
            )

    def completed_rounds(self) -> set[str]:
        completed: set[str] = set()
        for record in self.round_records():
            if record.get("error") is None and record.get("http_status") in range(200, 300):
                completed.add(str(record["round_key"]))
        return completed

    def attempts(self) -> dict[str, int]:
        attempts: dict[str, int] = {}
        for record in self.round_records():
            key = str(record.get("round_key"))
            attempts[key] = max(attempts.get(key, 0), int(record.get("attempt", 1)))
        return attempts

    def round_records(self) -> Iterable[dict[str, Any]]:
        if not self.paths.rounds.exists():
            return ()
        records: list[dict[str, Any]] = []
        with self.paths.rounds.open("r", encoding="utf-8") as handle:
            for line_number, line in enumerate(handle, start=1):
                if not line.strip():
                    continue
                try:
                    value = json.loads(line)
                except json.JSONDecodeError as exc:
                    raise RuntimeError(
                        f"invalid JSONL at {self.paths.rounds}:{line_number}: {exc}"
                    ) from exc
                if not isinstance(value, dict):
                    raise RuntimeError(
                        f"round record at {self.paths.rounds}:{line_number} is not an object"
                    )
                records.append(value)
        return records

    def append_round(self, record: Mapping[str, Any]) -> None:
        payload = (canonical_json(record) + "\n").encode("utf-8")
        with self.paths.rounds.open("ab", buffering=0) as handle:
            handle.write(payload)
            os.fsync(handle.fileno())

    def update_manifest(self, updates: Mapping[str, Any]) -> None:
        current = json.loads(self.paths.manifest.read_text(encoding="utf-8"))
        current.update(updates)
        atomic_write_json(self.paths.manifest, current)

    def write_checksums(self) -> None:
        targets = [
            self.paths.manifest,
            self.paths.plan,
            self.paths.rounds,
            self.paths.server_log,
        ]
        lines: list[str] = []
        for path in targets:
            if path.is_file():
                digest = hashlib.sha256(path.read_bytes()).hexdigest()
                lines.append(f"{digest}  {path.name}\n")
        atomic_write_bytes(self.paths.checksums, "".join(lines).encode("utf-8"))


def validate_identifier(value: str, label: str) -> str:
    if not value or any(char not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_.+" for char in value):
        raise ValueError(
            f"{label} may contain only letters, digits, dash, underscore, dot, and plus"
        )
    if value in (".", ".."):
        raise ValueError(f"invalid {label}: {value!r}")
    return value


def atomic_write_json(path: Path, value: Mapping[str, Any]) -> None:
    atomic_write_bytes(path, (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode("utf-8"))


def atomic_write_jsonl(path: Path, values: Iterable[Mapping[str, Any]]) -> None:
    data = "".join(canonical_json(value) + "\n" for value in values).encode("utf-8")
    atomic_write_bytes(path, data)


def atomic_write_bytes(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        with temporary.open("xb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass


def _paths(output_root: Path, session_id: str, run_id: str) -> RunPaths:
    session_id = validate_identifier(session_id, "session_id")
    run_id = validate_identifier(run_id, "run_id")
    session_root = output_root / session_id
    root = session_root / run_id
    return RunPaths(
        root=root,
        session_manifest=session_root / "session_manifest.json",
        manifest=root / "manifest.json",
        plan=root / "plan.jsonl",
        rounds=root / "rounds.jsonl",
        server_log=root / "server.log",
        checksums=root / "checksums.sha256",
        lock=root / ".run.lock",
    )
