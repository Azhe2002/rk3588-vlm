from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping

from .schema import GenerationOptions


@dataclass(frozen=True)
class Frame:
    frame_id: str
    path: Path
    ground_truth: str | None = None
    source_session_id: str | None = None
    source_width: int | None = None
    source_height: int | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class Dataset:
    dataset_id: str
    manifest_path: Path
    frames: tuple[Frame, ...]


@dataclass(frozen=True)
class Question:
    question_id: str
    text: str


@dataclass(frozen=True)
class Condition:
    condition_id: str
    generation: Mapping[str, Any] = field(default_factory=dict)
    question_ids: tuple[str, ...] = ()
    repetitions: int = 1
    metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ServerConfig:
    mode: str
    url: str
    command: tuple[str, ...] = ()
    startup_timeout_s: float = 180.0
    request_timeout_s: float = 300.0


@dataclass(frozen=True)
class ExperimentConfig:
    config_path: Path
    experiment_id: str
    dataset: Dataset
    system_prompt: str
    questions: tuple[Question, ...]
    base_generation: GenerationOptions
    conditions: tuple[Condition, ...]
    server: ServerConfig
    randomization_seed: int
    randomization_strategy: str
    inter_request_delay_s: float = 0.0
    continue_on_error: bool = True
    metadata: Mapping[str, Any] = field(default_factory=dict)


def _read_object(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ValueError(f"configuration file not found: {path}") from exc
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid JSON in {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise ValueError(f"top-level JSON value in {path} must be an object")
    return value


def load_dataset(path: Path) -> Dataset:
    path = path.resolve()
    raw = _read_object(path)
    dataset_id = _required_text(raw, "dataset_id", path)
    raw_frames = raw.get("frames")
    if not isinstance(raw_frames, list) or not raw_frames:
        raise ValueError(f"{path}: frames must be a non-empty list")

    frames: list[Frame] = []
    seen: set[str] = set()
    for index, item in enumerate(raw_frames):
        if not isinstance(item, dict):
            raise ValueError(f"{path}: frames[{index}] must be an object")
        frame_id = _required_text(item, "frame_id", path)
        if frame_id in seen:
            raise ValueError(f"{path}: duplicate frame_id {frame_id!r}")
        seen.add(frame_id)
        relative_path = _required_text(item, "path", path)
        frame_path = (path.parent / relative_path).resolve()
        if not frame_path.is_file():
            raise ValueError(f"{path}: frame does not exist: {frame_path}")
        ground_truth = item.get("ground_truth")
        if ground_truth is not None and ground_truth not in ("yes", "no"):
            raise ValueError(f"{path}: ground_truth must be yes, no, or null")
        metadata = item.get("metadata", {})
        if not isinstance(metadata, dict):
            raise ValueError(f"{path}: frame metadata must be an object")
        frames.append(
            Frame(
                frame_id=frame_id,
                path=frame_path,
                ground_truth=ground_truth,
                source_session_id=_optional_text(item, "source_session_id", path),
                source_width=_optional_positive_int(item, "source_width", path),
                source_height=_optional_positive_int(item, "source_height", path),
                metadata=metadata,
            )
        )
    return Dataset(dataset_id=dataset_id, manifest_path=path, frames=tuple(frames))


def load_experiment(path: Path) -> ExperimentConfig:
    path = path.resolve()
    raw = _read_object(path)
    experiment_id = _required_text(raw, "experiment_id", path)
    dataset_value = _required_text(raw, "dataset", path)
    dataset = load_dataset((path.parent / dataset_value).resolve())
    system_prompt = _required_text(raw, "system_prompt", path)

    raw_questions = raw.get("questions")
    if not isinstance(raw_questions, list) or not raw_questions:
        raise ValueError(f"{path}: questions must be a non-empty list")
    questions: list[Question] = []
    question_ids: set[str] = set()
    for index, item in enumerate(raw_questions):
        if not isinstance(item, dict):
            raise ValueError(f"{path}: questions[{index}] must be an object")
        question_id = _required_text(item, "id", path)
        if question_id in question_ids:
            raise ValueError(f"{path}: duplicate question id {question_id!r}")
        question_ids.add(question_id)
        questions.append(Question(question_id, _required_text(item, "text", path)))

    base_raw = raw.get("base_generation", {})
    if not isinstance(base_raw, dict):
        raise ValueError(f"{path}: base_generation must be an object")
    base_generation = GenerationOptions.from_mapping(base_raw)

    raw_conditions = raw.get("conditions")
    if not isinstance(raw_conditions, list) or not raw_conditions:
        raise ValueError(f"{path}: conditions must be a non-empty list")
    conditions: list[Condition] = []
    condition_ids: set[str] = set()
    generation_fields = set(base_generation.public_dict())
    for index, item in enumerate(raw_conditions):
        if not isinstance(item, dict):
            raise ValueError(f"{path}: conditions[{index}] must be an object")
        condition_id = _required_text(item, "id", path)
        if condition_id in condition_ids:
            raise ValueError(f"{path}: duplicate condition id {condition_id!r}")
        condition_ids.add(condition_id)
        generation = item.get("generation", {})
        if not isinstance(generation, dict):
            raise ValueError(f"{path}: condition generation must be an object")
        unknown_generation = set(generation) - generation_fields
        if unknown_generation:
            raise ValueError(
                f"{path}: condition {condition_id!r} has unknown generation fields: "
                f"{sorted(unknown_generation)}"
            )
        selected_questions = item.get("question_ids", [])
        if not isinstance(selected_questions, list) or not all(
            isinstance(value, str) for value in selected_questions
        ):
            raise ValueError(f"{path}: question_ids must be a list of strings")
        missing_questions = set(selected_questions) - question_ids
        if missing_questions:
            raise ValueError(f"{path}: unknown question ids: {sorted(missing_questions)}")
        repetitions = item.get("repetitions", 1)
        if not isinstance(repetitions, int) or isinstance(repetitions, bool) or repetitions < 1:
            raise ValueError(f"{path}: repetitions must be a positive integer")
        metadata = item.get("metadata", {})
        if not isinstance(metadata, dict):
            raise ValueError(f"{path}: condition metadata must be an object")
        merged = base_generation.public_dict()
        merged.update(generation)
        GenerationOptions.from_mapping(merged)
        conditions.append(
            Condition(
                condition_id=condition_id,
                generation=generation,
                question_ids=tuple(selected_questions),
                repetitions=repetitions,
                metadata=metadata,
            )
        )

    server_raw = raw.get("server")
    if not isinstance(server_raw, dict):
        raise ValueError(f"{path}: server must be an object")
    mode = server_raw.get("mode", "external")
    if mode not in ("external", "managed"):
        raise ValueError(f"{path}: server.mode must be external or managed")
    command = server_raw.get("command", [])
    if not isinstance(command, list) or not all(isinstance(value, str) for value in command):
        raise ValueError(f"{path}: server.command must be a list of strings")
    if mode == "managed" and not command:
        raise ValueError(f"{path}: managed server requires a command")
    server = ServerConfig(
        mode=mode,
        url=_required_text(server_raw, "url", path),
        command=tuple(command),
        startup_timeout_s=_positive_number(server_raw, "startup_timeout_s", 180.0, path),
        request_timeout_s=_positive_number(server_raw, "request_timeout_s", 300.0, path),
    )

    random_raw = raw.get("randomization", {})
    if not isinstance(random_raw, dict):
        raise ValueError(f"{path}: randomization must be an object")
    seed = random_raw.get("seed", 17001)
    if not isinstance(seed, int) or isinstance(seed, bool):
        raise ValueError(f"{path}: randomization.seed must be an integer")
    strategy = random_raw.get("strategy", "within-frame")
    if strategy not in ("within-frame", "global"):
        raise ValueError(f"{path}: randomization.strategy must be within-frame or global")

    metadata = raw.get("metadata", {})
    if not isinstance(metadata, dict):
        raise ValueError(f"{path}: metadata must be an object")
    return ExperimentConfig(
        config_path=path,
        experiment_id=experiment_id,
        dataset=dataset,
        system_prompt=system_prompt,
        questions=tuple(questions),
        base_generation=base_generation,
        conditions=tuple(conditions),
        server=server,
        randomization_seed=seed,
        randomization_strategy=strategy,
        inter_request_delay_s=_nonnegative_number(raw, "inter_request_delay_s", 0.0, path),
        continue_on_error=bool(raw.get("continue_on_error", True)),
        metadata=metadata,
    )


def merged_generation(config: ExperimentConfig, condition: Condition) -> GenerationOptions:
    merged = config.base_generation.public_dict()
    merged.update(condition.generation)
    return GenerationOptions.from_mapping(merged)


def _required_text(value: Mapping[str, Any], key: str, source: Path) -> str:
    item = value.get(key)
    if not isinstance(item, str) or not item.strip():
        raise ValueError(f"{source}: {key} must be a non-empty string")
    return item


def _optional_text(value: Mapping[str, Any], key: str, source: Path) -> str | None:
    item = value.get(key)
    if item is not None and (not isinstance(item, str) or not item.strip()):
        raise ValueError(f"{source}: {key} must be a non-empty string or null")
    return item


def _optional_positive_int(value: Mapping[str, Any], key: str, source: Path) -> int | None:
    item = value.get(key)
    if item is not None and (
        not isinstance(item, int) or isinstance(item, bool) or item <= 0
    ):
        raise ValueError(f"{source}: {key} must be a positive integer or null")
    return item


def _positive_number(value: Mapping[str, Any], key: str, default: float, source: Path) -> float:
    item = value.get(key, default)
    if not isinstance(item, (int, float)) or isinstance(item, bool) or item <= 0:
        raise ValueError(f"{source}: {key} must be a positive number")
    return float(item)


def _nonnegative_number(
    value: Mapping[str, Any], key: str, default: float, source: Path
) -> float:
    item = value.get(key, default)
    if not isinstance(item, (int, float)) or isinstance(item, bool) or item < 0:
        raise ValueError(f"{source}: {key} must be a non-negative number")
    return float(item)
