from __future__ import annotations

import hashlib
import json
import os
import platform
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from .config import ExperimentConfig, load_experiment
from .plan import PlanItem, build_plan
from .request_client import build_request
from .schema import SCHEMA_VERSION, GenerationOptions, classify_output, sha256_bytes, sha256_json
from .server import ServerLifecycle
from .storage import RunStore, atomic_write_json


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def local_now_id() -> str:
    return datetime.now().astimezone().strftime("%Y%m%dT%H%M%S%z")


def run_experiment(
    *,
    config_path: Path,
    output_root: Path,
    session_id: str | None,
    run_id: str | None,
    resume: bool,
    dry_run: bool,
) -> Path:
    config = load_experiment(config_path)
    session_id = session_id or f"{local_now_id()}_{platform.node() or 'host'}"
    run_id = run_id or config.experiment_id
    plan = build_plan(config)
    fingerprint = experiment_fingerprint(config)
    config_sha256 = sha256_bytes(config.config_path.read_bytes())
    plan_sha256 = sha256_json([item.as_dict() for item in plan])
    started = utc_now()

    session_manifest = {
        "schema_version": SCHEMA_VERSION,
        "session_id": session_id,
        "created_at_utc": started,
        "host": host_snapshot(),
        "git": git_snapshot(config.config_path.parent),
    }
    manifest: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "session_id": session_id,
        "run_id": run_id,
        "experiment_id": config.experiment_id,
        "dataset_id": config.dataset.dataset_id,
        "config_path": str(config.config_path),
        "config_sha256": config_sha256,
        "experiment_fingerprint": fingerprint,
        "plan_sha256": plan_sha256,
        "randomization_seed": config.randomization_seed,
        "randomization_strategy": config.randomization_strategy,
        "planned_rounds": len(plan),
        "started_at_utc": started,
        "status": "planned" if dry_run else "running",
        "metadata": dict(config.metadata),
        "process_pid": os.getpid(),
    }

    with RunStore(output_root, session_id, run_id, resume) as store:
        store.initialize(
            session_manifest=session_manifest,
            manifest=manifest,
            plan=(item.as_dict() for item in plan),
        )
        if dry_run:
            store.update_manifest({"status": "planned", "finished_at_utc": utc_now()})
            store.write_checksums()
            return store.paths.root

        completed = store.completed_rounds()
        attempts = store.attempts()
        status = "complete"
        try:
            with ServerLifecycle(config.server, store.paths.server_log) as server:
                store.update_manifest(server.manifest_fields())
                for item in plan:
                    if item.round_key in completed:
                        continue
                    attempt = attempts.get(item.round_key, 0) + 1
                    record = execute_round(
                        config=config,
                        item=item,
                        attempt=attempt,
                        session_id=session_id,
                        run_id=run_id,
                        client=server.client,
                    )
                    store.append_round(record)
                    outcome = "ok" if record["error"] is None else f"error: {record['error']}"
                    print(
                        f"[{item.plan_index:04d}/{len(plan):04d}] "
                        f"{item.round_key} attempt={attempt} {outcome}",
                        flush=True,
                    )
                    if record["error"] is not None and not config.continue_on_error:
                        raise RuntimeError(str(record["error"]))
                    if config.inter_request_delay_s:
                        time.sleep(config.inter_request_delay_s)
        except KeyboardInterrupt:
            status = "interrupted"
            raise
        except BaseException:
            status = "failed"
            raise
        finally:
            records = list(store.round_records())
            successful = {
                str(record["round_key"])
                for record in records
                if record.get("error") is None
                and isinstance(record.get("http_status"), int)
                and 200 <= int(record["http_status"]) < 300
            }
            if status == "complete" and len(successful) != len(plan):
                status = "partial"
            store.update_manifest(
                {
                    "status": status,
                    "finished_at_utc": utc_now(),
                    "record_count": len(records),
                    "successful_rounds": len(successful),
                    "remaining_rounds": len(plan) - len(successful),
                }
            )
            store.write_checksums()
        return store.paths.root


def execute_round(
    *,
    config: ExperimentConfig,
    item: PlanItem,
    attempt: int,
    session_id: str,
    run_id: str,
    client: Any,
) -> dict[str, Any]:
    requested_at = utc_now()
    base: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "session_id": session_id,
        "run_id": run_id,
        "round_id": item.plan_index,
        "round_key": item.round_key,
        "attempt": attempt,
        "condition_id": item.condition_id,
        "condition_metadata": item.condition_metadata,
        "timestamp_utc": requested_at,
        "frame_id": item.frame_id,
        "frame_path": item.frame_path,
        "source_frame_id": item.source_frame_id,
        "transform_id": item.transform_id,
        "frame_bytes": None,
        "frame_sha256": None,
        "source_session_id": item.source_session_id,
        "source_width": item.source_width,
        "source_height": item.source_height,
        "frame_metadata": item.frame_metadata,
        "ground_truth": item.ground_truth,
        "question_id": item.question_id,
        "question": item.question,
        "repetition": item.repetition,
        **item.generation,
        "request_payload_sha256": None,
        "request_audit": None,
        "http_status": None,
        "latency_ms": None,
        "raw_output": None,
        "format_class": "noncompliant",
        "format_exact": False,
        "format_word": False,
        "semantic_label": "unknown",
        "semantic_correct": None,
        "prompt_tokens": None,
        "cached_tokens": None,
        "completion_tokens": None,
        "timings": None,
        "response": None,
        "error": None,
    }
    try:
        image_bytes = Path(item.frame_path).read_bytes()
        options = GenerationOptions.from_mapping(item.generation)
        prepared = build_request(
            image_bytes=image_bytes,
            system_prompt=config.system_prompt,
            question=item.question,
            options=options,
        )
        base.update(
            {
                "frame_bytes": len(image_bytes),
                "frame_sha256": prepared.frame_sha256,
                "request_payload_sha256": prepared.payload_sha256,
                "request_audit": prepared.audit_payload,
            }
        )
        result = client.complete(prepared)
        base.update(
            {
                "http_status": result.status,
                "latency_ms": result.latency_ms,
                "raw_output": result.output,
                "response": result.response,
                "error": result.error,
            }
        )
        if result.output is not None:
            base.update(classify_output(result.output, item.ground_truth))
        usage = extract_usage(result.response)
        base.update(usage)
        if result.response is not None:
            base["timings"] = result.response.get("timings")
    except Exception as exc:
        base["error"] = f"{type(exc).__name__}: {exc}"
    return base


def extract_usage(response: Mapping[str, Any] | None) -> dict[str, int | None]:
    result: dict[str, int | None] = {
        "prompt_tokens": None,
        "cached_tokens": None,
        "completion_tokens": None,
    }
    if response is None:
        return result
    usage = response.get("usage")
    if not isinstance(usage, Mapping):
        usage = {}
    timings = response.get("timings")
    if not isinstance(timings, Mapping):
        timings = {}
    aliases = {
        "prompt_tokens": ("prompt_tokens", "prompt_n"),
        "cached_tokens": ("cached_tokens", "prompt_cached_tokens"),
        "completion_tokens": ("completion_tokens", "predicted_n"),
    }
    for target, names in aliases.items():
        for source in (usage, timings):
            for name in names:
                value = source.get(name)
                if isinstance(value, int) and not isinstance(value, bool):
                    result[target] = value
                    break
            if result[target] is not None:
                break
    return result


def experiment_fingerprint(config: ExperimentConfig) -> str:
    digest = hashlib.sha256()
    for path in (config.config_path, config.dataset.manifest_path):
        digest.update(str(path).encode("utf-8"))
        digest.update(path.read_bytes())
    for frame in sorted(config.dataset.frames, key=lambda value: value.frame_id):
        digest.update(frame.frame_id.encode("utf-8"))
        digest.update(hashlib.sha256(frame.path.read_bytes()).digest())
    return digest.hexdigest()


def host_snapshot() -> dict[str, Any]:
    return {
        "node": platform.node(),
        "platform": platform.platform(),
        "python": platform.python_version(),
        "machine": platform.machine(),
        "processor": platform.processor(),
    }


def git_snapshot(start: Path) -> dict[str, Any]:
    root = _git(start, "rev-parse", "--show-toplevel")
    if root is None:
        return {"available": False}
    commit = _git(Path(root), "rev-parse", "HEAD")
    status = _git(Path(root), "status", "--porcelain")
    return {
        "available": True,
        "root": root,
        "commit": commit,
        "dirty": bool(status),
        "status_porcelain": status.splitlines() if status else [],
    }


def _git(cwd: Path, *args: str) -> str | None:
    try:
        result = subprocess.run(
            ["git", *args],
            cwd=cwd,
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return result.stdout.strip()
