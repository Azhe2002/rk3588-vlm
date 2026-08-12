from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .request_client import YES_NO_GRAMMAR, YES_NO_JSON_SCHEMA, LlamaHttpClient, build_request
from .schema import ConstraintMode, ContentOrder, GenerationOptions
from .storage import atomic_write_json


def probe_server(
    *,
    server_url: str,
    image_path: Path,
    output_path: Path,
    system_prompt: str,
    question: str,
    timeout_s: float,
) -> dict[str, Any]:
    image = image_path.read_bytes()
    client = LlamaHttpClient(server_url, timeout_s)
    cases = {
        "baseline": GenerationOptions(),
        "seed": GenerationOptions(seed=77331),
        "cache_prompt_false": GenerationOptions(cache_prompt=False),
        "n_probs": GenerationOptions(n_probs=5),
        "grammar": GenerationOptions(
            constraint=ConstraintMode.GRAMMAR,
            grammar=YES_NO_GRAMMAR,
        ),
        "json_schema": GenerationOptions(
            constraint=ConstraintMode.JSON_SCHEMA,
            response_schema=YES_NO_JSON_SCHEMA,
        ),
    }
    results: dict[str, Any] = {}
    for name, options in cases.items():
        prepared = build_request(
            image_bytes=image,
            system_prompt=system_prompt,
            question=question,
            options=options,
        )
        response = client.complete(prepared)
        results[name] = {
            "accepted": response.status is not None and 200 <= response.status < 300,
            "http_status": response.status,
            "latency_ms": response.latency_ms,
            "output": response.output,
            "error": response.error,
            "response": response.response,
            "request_payload_sha256": prepared.payload_sha256,
        }
    baseline_response = results["baseline"].get("response") or {}
    results["observed_response_fields"] = {
        "usage": "usage" in baseline_response,
        "timings": "timings" in baseline_response,
        "cached_tokens": "cached_tokens" in (baseline_response.get("usage") or {}),
    }
    report = {
        "schema_version": 1,
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "server_url": server_url,
        "image_path": str(image_path.resolve()),
        "note": "accepted means the server returned 2xx; it does not prove the field affected decoding",
        "results": results,
    }
    if output_path.exists():
        raise FileExistsError(output_path)
    atomic_write_json(output_path, report)
    return report
