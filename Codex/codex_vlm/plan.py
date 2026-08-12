from __future__ import annotations

import random
from dataclasses import asdict, dataclass
from typing import Any, Iterable

from .config import ExperimentConfig, merged_generation


@dataclass(frozen=True)
class PlanItem:
    plan_index: int
    round_key: str
    frame_id: str
    frame_path: str
    source_frame_id: str
    transform_id: str
    ground_truth: str | None
    source_session_id: str | None
    source_width: int | None
    source_height: int | None
    frame_metadata: dict[str, Any]
    condition_id: str
    condition_metadata: dict[str, Any]
    question_id: str
    question: str
    repetition: int
    generation: dict[str, Any]

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def build_plan(config: ExperimentConfig) -> list[PlanItem]:
    questions = {question.question_id: question for question in config.questions}
    rows: list[dict[str, Any]] = []
    for frame in config.dataset.frames:
        source_frame_id = str(frame.metadata.get("source_frame_id", frame.frame_id))
        transform_id = str(frame.metadata.get("transform_id", "raw"))
        frame_rows: list[dict[str, Any]] = []
        for condition in config.conditions:
            selected_questions = condition.question_ids or tuple(questions)
            generation = merged_generation(config, condition).public_dict()
            for question_id in selected_questions:
                for repetition in range(1, condition.repetitions + 1):
                    round_key = "/".join(
                        (frame.frame_id, condition.condition_id, question_id, str(repetition))
                    )
                    frame_rows.append(
                        {
                            "round_key": round_key,
                            "frame_id": frame.frame_id,
                            "frame_path": str(frame.path),
                            "source_frame_id": source_frame_id,
                            "transform_id": transform_id,
                            "ground_truth": frame.ground_truth,
                            "source_session_id": frame.source_session_id,
                            "source_width": frame.source_width,
                            "source_height": frame.source_height,
                            "frame_metadata": dict(frame.metadata),
                            "condition_id": condition.condition_id,
                            "condition_metadata": dict(condition.metadata),
                            "question_id": question_id,
                            "question": questions[question_id].text,
                            "repetition": repetition,
                            "generation": generation,
                        }
                    )
        rows.extend(_randomize_frame_rows(config, frame.frame_id, frame_rows))

    if config.randomization_strategy == "global":
        random.Random(config.randomization_seed).shuffle(rows)

    return [PlanItem(plan_index=index, **row) for index, row in enumerate(rows, start=1)]


def _randomize_frame_rows(
    config: ExperimentConfig, frame_id: str, rows: list[dict[str, Any]]
) -> Iterable[dict[str, Any]]:
    if config.randomization_strategy != "within-frame":
        return rows
    stable_frame_seed = sum((index + 1) * ord(char) for index, char in enumerate(frame_id))
    random.Random(config.randomization_seed ^ stable_frame_seed).shuffle(rows)
    return rows
