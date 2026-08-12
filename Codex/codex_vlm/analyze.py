from __future__ import annotations

import csv
import json
import math
import statistics
from collections import defaultdict
from dataclasses import dataclass
from itertools import combinations
from pathlib import Path
from typing import Any, Iterable, Mapping

from .storage import atomic_write_json


@dataclass(frozen=True)
class Arm:
    condition_id: str
    question_id: str

    @property
    def name(self) -> str:
        return f"{self.condition_id}::{self.question_id}"


def analyze_runs(round_files: Iterable[Path], output_dir: Path) -> dict[str, Any]:
    records = latest_successful(load_records(round_files))
    if not records:
        raise ValueError("no successful round records were found")
    if output_dir.exists():
        raise FileExistsError(f"analysis output already exists: {output_dir}")
    output_dir.mkdir(parents=True)

    summary_rows = summarize(records)
    transition_rows = pairwise_transitions(records)
    session_rows = summarize_sessions(records)
    write_csv(output_dir / "summary.csv", summary_rows)
    write_csv(output_dir / "transitions.csv", transition_rows)
    write_csv(output_dir / "sessions.csv", session_rows)
    result = {
        "record_count": len(records),
        "arm_count": len(summary_rows),
        "summary": summary_rows,
        "transitions": transition_rows,
        "sessions": session_rows,
    }
    atomic_write_json(output_dir / "summary.json", result)
    return result


def load_records(paths: Iterable[Path]) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for path in paths:
        with path.open("r", encoding="utf-8") as handle:
            for line_number, line in enumerate(handle, start=1):
                if not line.strip():
                    continue
                try:
                    record = json.loads(line)
                except json.JSONDecodeError as exc:
                    raise ValueError(f"invalid JSONL at {path}:{line_number}: {exc}") from exc
                if isinstance(record, dict):
                    record["_source_file"] = str(path)
                    records.append(record)
    return records


def latest_successful(records: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    selected: dict[tuple[str, str, str], dict[str, Any]] = {}
    for record in records:
        status = record.get("http_status")
        if record.get("error") is not None or not isinstance(status, int) or not 200 <= status < 300:
            continue
        identity = (
            str(record.get("session_id")),
            str(record.get("run_id")),
            str(record.get("round_key")),
        )
        current = selected.get(identity)
        if current is None or int(record.get("attempt", 1)) > int(current.get("attempt", 1)):
            selected[identity] = record
    return list(selected.values())


def summarize(records: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    groups: dict[Arm, list[Mapping[str, Any]]] = defaultdict(list)
    for record in records:
        groups[Arm(str(record["condition_id"]), str(record["question_id"]))].append(record)
    rows: list[dict[str, Any]] = []
    for arm in sorted(groups, key=lambda item: item.name):
        values = groups[arm]
        n = len(values)
        exact = sum(bool(value.get("format_exact")) for value in values)
        word = sum(bool(value.get("format_word")) for value in values)
        known_correct = [
            bool(value["semantic_correct"])
            for value in values
            if value.get("semantic_correct") is not None
        ]
        semantic_counts = {
            label: sum(value.get("semantic_label") == label for value in values)
            for label in ("yes", "no", "unknown")
        }
        word_low, word_high = wilson_interval(word, n)
        correct = sum(known_correct)
        correct_low, correct_high = wilson_interval(correct, len(known_correct))
        latencies = [
            float(value["latency_ms"])
            for value in values
            if isinstance(value.get("latency_ms"), (int, float))
        ]
        rows.append(
            {
                "arm": arm.name,
                "condition_id": arm.condition_id,
                "question_id": arm.question_id,
                "n": n,
                "format_exact_n": exact,
                "format_exact_rate": exact / n,
                "format_word_n": word,
                "format_word_rate": word / n,
                "format_word_ci95_low": word_low,
                "format_word_ci95_high": word_high,
                "semantic_known_n": len(known_correct),
                "semantic_correct_n": correct,
                "semantic_correct_rate": correct / len(known_correct) if known_correct else None,
                "semantic_correct_ci95_low": correct_low,
                "semantic_correct_ci95_high": correct_high,
                "semantic_yes_n": semantic_counts["yes"],
                "semantic_no_n": semantic_counts["no"],
                "semantic_unknown_n": semantic_counts["unknown"],
                "latency_ms_mean": statistics.fmean(latencies) if latencies else None,
                "latency_ms_median": statistics.median(latencies) if latencies else None,
            }
        )
    return rows


def summarize_sessions(records: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    groups: dict[tuple[str, str], list[Mapping[str, Any]]] = defaultdict(list)
    for record in records:
        source_session = str(record.get("source_session_id") or record.get("session_id"))
        arm = Arm(str(record["condition_id"]), str(record["question_id"])).name
        groups[(source_session, arm)].append(record)
    rows: list[dict[str, Any]] = []
    for (source_session, arm), values in sorted(groups.items()):
        known = [value for value in values if value.get("semantic_correct") is not None]
        rows.append(
            {
                "source_session_id": source_session,
                "arm": arm,
                "n": len(values),
                "format_word_rate": sum(bool(value.get("format_word")) for value in values)
                / len(values),
                "semantic_correct_rate": (
                    sum(bool(value["semantic_correct"]) for value in known) / len(known)
                    if known
                    else None
                ),
            }
        )
    return rows


def pairwise_transitions(records: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    by_arm: dict[Arm, dict[tuple[str, str, str, int], Mapping[str, Any]]] = defaultdict(dict)
    for record in records:
        arm = Arm(str(record["condition_id"]), str(record["question_id"]))
        key = (
            str(record.get("session_id")),
            str(record.get("run_id")),
            str(record["frame_id"]),
            int(record.get("repetition", 1)),
        )
        if key in by_arm[arm]:
            raise ValueError(f"duplicate paired observation for {arm.name} and {key}")
        by_arm[arm][key] = record

    rows: list[dict[str, Any]] = []
    for arm_a, arm_b in combinations(sorted(by_arm, key=lambda item: item.name), 2):
        common = sorted(set(by_arm[arm_a]) & set(by_arm[arm_b]))
        if not common:
            continue
        row: dict[str, Any] = {
            "arm_a": arm_a.name,
            "arm_b": arm_b.name,
            "paired_n": len(common),
        }
        for metric in ("format_word", "semantic_correct"):
            pairs = [
                (by_arm[arm_a][key].get(metric), by_arm[arm_b][key].get(metric))
                for key in common
            ]
            pairs = [(bool(a), bool(b)) for a, b in pairs if a is not None and b is not None]
            n00 = sum(not a and not b for a, b in pairs)
            n01 = sum(not a and b for a, b in pairs)
            n10 = sum(a and not b for a, b in pairs)
            n11 = sum(a and b for a, b in pairs)
            row.update(
                {
                    f"{metric}_paired_n": len(pairs),
                    f"{metric}_00": n00,
                    f"{metric}_01": n01,
                    f"{metric}_10": n10,
                    f"{metric}_11": n11,
                    f"{metric}_delta_b_minus_a": ((n01 - n10) / len(pairs)) if pairs else None,
                    f"{metric}_mcnemar_exact_p": mcnemar_exact(n01, n10),
                }
            )
        rows.append(row)
    return rows


def wilson_interval(successes: int, total: int, z: float = 1.959963984540054) -> tuple[float | None, float | None]:
    if total == 0:
        return None, None
    proportion = successes / total
    denominator = 1 + z * z / total
    centre = (proportion + z * z / (2 * total)) / denominator
    margin = (
        z
        * math.sqrt(proportion * (1 - proportion) / total + z * z / (4 * total * total))
        / denominator
    )
    return max(0.0, centre - margin), min(1.0, centre + margin)


def mcnemar_exact(n01: int, n10: int) -> float | None:
    discordant = n01 + n10
    if discordant == 0:
        return 1.0
    tail = min(n01, n10)
    probability = sum(math.comb(discordant, value) for value in range(tail + 1)) / (2**discordant)
    return min(1.0, 2 * probability)


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    fieldnames: list[str] = []
    for row in rows:
        for key in row:
            if key not in fieldnames:
                fieldnames.append(key)
    with path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
