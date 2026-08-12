from __future__ import annotations

import base64
import json
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any, Mapping

from .schema import ConstraintMode, ContentOrder, GenerationOptions, sha256_bytes, sha256_json


YES_NO_GRAMMAR = 'root ::= ("Yes" | "No" | "yes" | "no") "."?'
YES_NO_JSON_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {"answer": {"type": "string", "enum": ["yes", "no"]}},
    "required": ["answer"],
    "additionalProperties": False,
}


@dataclass(frozen=True)
class PreparedRequest:
    payload: dict[str, Any]
    audit_payload: dict[str, Any]
    payload_sha256: str
    frame_sha256: str


@dataclass(frozen=True)
class HttpResult:
    status: int | None
    latency_ms: int
    response: Mapping[str, Any] | None
    raw_body: str
    output: str | None
    error: str | None


def _image_part(image_bytes: bytes, mime_type: str) -> dict[str, Any]:
    encoded = base64.b64encode(image_bytes).decode("ascii")
    return {
        "type": "image_url",
        "image_url": {"url": f"data:{mime_type};base64,{encoded}"},
    }


def build_request(
    *,
    image_bytes: bytes,
    system_prompt: str,
    question: str,
    options: GenerationOptions,
    mime_type: str = "image/jpeg",
) -> PreparedRequest:
    if not image_bytes:
        raise ValueError("image_bytes cannot be empty")
    if not system_prompt.strip() or not question.strip():
        raise ValueError("system_prompt and question cannot be empty")

    image_part = _image_part(image_bytes, mime_type)
    text_part = {"type": "text", "text": question}
    if options.content_order is ContentOrder.TEXT_IMAGE:
        user_content = [text_part, image_part]
    else:
        user_content = [image_part, text_part]

    payload: dict[str, Any] = {
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content},
        ],
        "temperature": options.temperature,
        "max_tokens": options.max_tokens,
        "seed": options.seed,
        "cache_prompt": options.cache_prompt,
        "stream": False,
    }
    if options.n_probs is not None:
        payload["n_probs"] = options.n_probs
    if options.constraint is ConstraintMode.GRAMMAR:
        payload["grammar"] = options.grammar
    elif options.constraint is ConstraintMode.JSON_SCHEMA:
        payload["response_format"] = {
            "type": "json_schema",
            "schema": options.response_schema,
        }

    frame_sha256 = sha256_bytes(image_bytes)
    audit_payload = json.loads(json.dumps(payload))
    audit_user_content = audit_payload["messages"][1]["content"]
    for item in audit_user_content:
        if item.get("type") == "image_url":
            item["image_url"]["url"] = f"sha256:{frame_sha256}"

    return PreparedRequest(
        payload=payload,
        audit_payload=audit_payload,
        payload_sha256=sha256_json(payload),
        frame_sha256=frame_sha256,
    )


def extract_output(response: Mapping[str, Any]) -> str | None:
    try:
        content = response["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError):
        return None
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        texts = [item.get("text", "") for item in content if isinstance(item, Mapping)]
        return "".join(texts) or None
    return None


class LlamaHttpClient:
    def __init__(self, server_url: str, timeout_s: float = 300.0) -> None:
        self.server_url = server_url.rstrip("/")
        self.timeout_s = timeout_s

    @property
    def completions_url(self) -> str:
        return f"{self.server_url}/v1/chat/completions"

    def health(self) -> tuple[bool, str]:
        for suffix in ("/health", "/v1/models"):
            try:
                with urllib.request.urlopen(
                    f"{self.server_url}{suffix}", timeout=min(self.timeout_s, 10.0)
                ) as response:
                    body = response.read().decode("utf-8", "replace")
                    if 200 <= response.status < 300:
                        return True, body
            except (OSError, urllib.error.URLError):
                continue
        return False, "server did not answer /health or /v1/models"

    def complete(self, prepared: PreparedRequest) -> HttpResult:
        body = json.dumps(prepared.payload, ensure_ascii=False).encode("utf-8")
        request = urllib.request.Request(
            self.completions_url,
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        started = time.monotonic()
        try:
            with urllib.request.urlopen(request, timeout=self.timeout_s) as response:
                raw_body = response.read().decode("utf-8", "replace")
                status = response.status
        except urllib.error.HTTPError as exc:
            raw_body = exc.read().decode("utf-8", "replace")
            return HttpResult(
                status=exc.code,
                latency_ms=round((time.monotonic() - started) * 1000),
                response=_try_json(raw_body),
                raw_body=raw_body,
                output=None,
                error=f"HTTP {exc.code}: {exc.reason}",
            )
        except (OSError, urllib.error.URLError, TimeoutError) as exc:
            return HttpResult(
                status=None,
                latency_ms=round((time.monotonic() - started) * 1000),
                response=None,
                raw_body="",
                output=None,
                error=f"{type(exc).__name__}: {exc}",
            )

        decoded = _try_json(raw_body)
        if decoded is None:
            return HttpResult(
                status=status,
                latency_ms=round((time.monotonic() - started) * 1000),
                response=None,
                raw_body=raw_body,
                output=None,
                error="response was not valid JSON",
            )
        output = extract_output(decoded)
        return HttpResult(
            status=status,
            latency_ms=round((time.monotonic() - started) * 1000),
            response=decoded,
            raw_body=raw_body,
            output=output,
            error=None if output is not None else "response did not contain assistant content",
        )


def _try_json(raw: str) -> Mapping[str, Any] | None:
    try:
        value = json.loads(raw)
    except json.JSONDecodeError:
        return None
    return value if isinstance(value, Mapping) else None
