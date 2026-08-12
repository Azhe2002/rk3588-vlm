from __future__ import annotations

import dataclasses
import hashlib
import json
import re
from dataclasses import dataclass
from enum import Enum
from typing import Any, Mapping


SCHEMA_VERSION = 1


class ContentOrder(str, Enum):
    TEXT_IMAGE = "text-image"
    IMAGE_TEXT = "image-text"


class ConstraintMode(str, Enum):
    NONE = "none"
    GRAMMAR = "grammar"
    JSON_SCHEMA = "json-schema"


class FormatClass(str, Enum):
    EXACT = "exact"
    WORD = "word"
    NONCOMPLIANT = "noncompliant"


class SemanticClass(str, Enum):
    YES = "yes"
    NO = "no"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class GenerationOptions:
    temperature: float = 0.0
    max_tokens: int = 16
    seed: int = 17001
    cache_prompt: bool = False
    content_order: ContentOrder = ContentOrder.TEXT_IMAGE
    constraint: ConstraintMode = ConstraintMode.NONE
    n_probs: int | None = None
    grammar: str | None = None
    response_schema: Mapping[str, Any] | None = None

    def __post_init__(self) -> None:
        if not 0.0 <= self.temperature <= 2.0:
            raise ValueError("temperature must be in [0, 2]")
        if not 1 <= self.max_tokens <= 4096:
            raise ValueError("max_tokens must be in [1, 4096]")
        if self.n_probs is not None and self.n_probs < 0:
            raise ValueError("n_probs cannot be negative")
        if self.constraint is ConstraintMode.GRAMMAR and not self.grammar:
            raise ValueError("grammar constraint requires grammar text")
        if self.constraint is ConstraintMode.JSON_SCHEMA and not self.response_schema:
            raise ValueError("json-schema constraint requires response_schema")

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "GenerationOptions":
        fields = {field.name for field in dataclasses.fields(cls)}
        unknown = set(value) - fields
        if unknown:
            raise ValueError(f"unknown generation options: {sorted(unknown)}")
        data = dict(value)
        if "content_order" in data:
            data["content_order"] = ContentOrder(data["content_order"])
        if "constraint" in data:
            data["constraint"] = ConstraintMode(data["constraint"])
        return cls(**data)

    def public_dict(self) -> dict[str, Any]:
        result = dataclasses.asdict(self)
        result["content_order"] = self.content_order.value
        result["constraint"] = self.constraint.value
        return result


_WORD_RE = re.compile(r"^\s*(yes|no)\s*([.!?])?\s*$", re.IGNORECASE)
_YES_TOKEN_RE = re.compile(r"\byes\b", re.IGNORECASE)
_NO_TOKEN_RE = re.compile(r"\bno\b", re.IGNORECASE)

_NEGATIVE_PATTERNS = (
    re.compile(r"\bthere\s+(?:is|are)\s+(?:not|no)\b", re.IGNORECASE),
    re.compile(r"\b(?:is|are|was|were)\s+not\s+(?:visible|present|shown)\b", re.IGNORECASE),
    re.compile(r"\b(?:do|does|did|can|could)\s+not\s+(?:see|detect|find|identify)\b", re.IGNORECASE),
    re.compile(r"\b(?:cannot|can't|isn't|aren't)\s+(?:see|detect|find|visible|present)\b", re.IGNORECASE),
    re.compile(r"^\s*no\s+\w", re.IGNORECASE),
    re.compile(r"\b(?:absent|missing|not detected|not visible)\b", re.IGNORECASE),
)

_POSITIVE_PATTERNS = (
    re.compile(r"\bthere\s+(?:is|are)\s+(?:a|an|the|one|some)\b", re.IGNORECASE),
    re.compile(r"\b(?:is|are)\s+(?:clearly\s+)?(?:visible|present|shown)\b", re.IGNORECASE),
    re.compile(r"\b(?:can|could)\s+(?:clearly\s+)?(?:see|detect|identify)\b", re.IGNORECASE),
    re.compile(r"\bimage\s+(?:contains|shows|depicts)\b", re.IGNORECASE),
)

_META_OR_CONDITIONAL_PATTERNS = (
    re.compile(r"^\s*(?:if|whether)\b", re.IGNORECASE),
    re.compile(r"\banswer\s+(?:with\s+|only\s+)?(?:yes|no)\b", re.IGNORECASE),
    re.compile(r"\brespond\s+(?:with\s+)?(?:yes|no)\b", re.IGNORECASE),
)


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_json(value: Any) -> str:
    return sha256_bytes(canonical_json(value).encode("utf-8"))


def classify_format(raw: str) -> FormatClass:
    if raw in ("yes", "no"):
        return FormatClass.EXACT
    if _WORD_RE.fullmatch(raw):
        return FormatClass.WORD
    return FormatClass.NONCOMPLIANT


def classify_semantic(raw: str) -> SemanticClass:
    match = _WORD_RE.fullmatch(raw)
    if match:
        return SemanticClass(match.group(1).lower())

    text = " ".join(raw.strip().split())
    if not text or any(pattern.search(text) for pattern in _META_OR_CONDITIONAL_PATTERNS):
        return SemanticClass.UNKNOWN

    has_yes = bool(_YES_TOKEN_RE.search(text))
    has_no = bool(_NO_TOKEN_RE.search(text))
    if has_yes and has_no:
        return SemanticClass.UNKNOWN
    if any(pattern.search(text) for pattern in _NEGATIVE_PATTERNS):
        return SemanticClass.NO
    if any(pattern.search(text) for pattern in _POSITIVE_PATTERNS):
        return SemanticClass.YES
    if has_yes:
        return SemanticClass.YES
    if has_no:
        return SemanticClass.NO
    return SemanticClass.UNKNOWN


def semantic_correct(label: SemanticClass, ground_truth: str | None) -> bool | None:
    if ground_truth is None or label is SemanticClass.UNKNOWN:
        return None
    truth = SemanticClass(ground_truth)
    if truth is SemanticClass.UNKNOWN:
        return None
    return label is truth


def classify_output(raw: str, ground_truth: str | None = None) -> dict[str, Any]:
    format_class = classify_format(raw)
    semantic_label = classify_semantic(raw)
    return {
        "format_class": format_class.value,
        "format_exact": format_class is FormatClass.EXACT,
        "format_word": format_class in (FormatClass.EXACT, FormatClass.WORD),
        "semantic_label": semantic_label.value,
        "semantic_correct": semantic_correct(semantic_label, ground_truth),
    }
