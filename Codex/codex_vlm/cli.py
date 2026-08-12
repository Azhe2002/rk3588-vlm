from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Sequence

from .reporting import analyze_runs
from .capture import capture_frames
from .config import load_experiment
from .dataset_tools import freeze_directory, transform_dataset
from .plan import build_plan
from .probe import probe_server
from .runner import run_experiment


DEFAULT_SYSTEM_PROMPT = (
    "You are an expert in recognition, processing, and analysis. "
    "Please carefully analyze the image and answer the question accurately. "
    "Please respond with only 'yes' or 'no'."
)
DEFAULT_QUESTION = "Is the target object present? Please answer only yes or no."


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(prog="rkvlm-exp", description="RK3588 VLM experiment runner")
    subcommands = root.add_subparsers(dest="command", required=True)

    validate = subcommands.add_parser("validate", help="validate a JSON experiment configuration")
    validate.add_argument("config", type=Path)

    plan = subcommands.add_parser("plan", help="print the deterministic randomized plan")
    plan.add_argument("config", type=Path)

    run = subcommands.add_parser("run", help="execute or resume an experiment")
    run.add_argument("config", type=Path)
    run.add_argument("--output-root", type=Path, default=Path("data"))
    run.add_argument("--session-id")
    run.add_argument("--run-id")
    run.add_argument("--resume", action="store_true")
    run.add_argument("--dry-run", action="store_true")

    analyze = subcommands.add_parser("analyze", help="summarize JSONL rounds")
    analyze.add_argument("rounds", type=Path, nargs="+")
    analyze.add_argument("--output", type=Path, required=True)

    freeze = subcommands.add_parser("freeze", help="copy images into an immutable dataset")
    freeze.add_argument("source", type=Path)
    freeze.add_argument("output", type=Path)
    freeze.add_argument("--dataset-id", required=True)
    freeze.add_argument("--ground-truth", choices=("yes", "no"))
    freeze.add_argument("--source-session-id")

    transform = subcommands.add_parser("transform", help="generate paired image variants")
    transform.add_argument("dataset", type=Path)
    transform.add_argument("spec", type=Path)
    transform.add_argument("output", type=Path)

    capture = subcommands.add_parser("capture", help="capture exact JPEG frames on Linux")
    capture.add_argument("output", type=Path)
    capture.add_argument("--dataset-id", required=True)
    capture.add_argument("--source-session-id", required=True)
    capture.add_argument("--count", type=int, default=20)
    capture.add_argument("--interval", type=float, default=0.0)
    capture.add_argument("--ground-truth", choices=("yes", "no"))
    capture.add_argument("--width", type=int)
    capture.add_argument("--height", type=int)
    capture.add_argument(
        "--command",
        nargs=argparse.REMAINDER,
        required=True,
        help="argv template containing {output}; put this option last",
    )

    probe = subcommands.add_parser("probe", help="probe llama-server request capabilities")
    probe.add_argument("--server-url", default="http://127.0.0.1:8088")
    probe.add_argument("--image", type=Path, required=True)
    probe.add_argument("--output", type=Path, required=True)
    probe.add_argument("--system-prompt", default=DEFAULT_SYSTEM_PROMPT)
    probe.add_argument("--question", default=DEFAULT_QUESTION)
    probe.add_argument("--timeout", type=float, default=300.0)
    return root


def main(argv: Sequence[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        if args.command == "validate":
            config = load_experiment(args.config)
            plan = build_plan(config)
            print(
                json.dumps(
                    {
                        "experiment_id": config.experiment_id,
                        "dataset_id": config.dataset.dataset_id,
                        "frames": len(config.dataset.frames),
                        "conditions": len(config.conditions),
                        "rounds": len(plan),
                    },
                    ensure_ascii=False,
                    indent=2,
                )
            )
        elif args.command == "plan":
            for item in build_plan(load_experiment(args.config)):
                print(json.dumps(item.as_dict(), ensure_ascii=False, sort_keys=True))
        elif args.command == "run":
            output = run_experiment(
                config_path=args.config,
                output_root=args.output_root,
                session_id=args.session_id,
                run_id=args.run_id,
                resume=args.resume,
                dry_run=args.dry_run,
            )
            print(output)
        elif args.command == "analyze":
            result = analyze_runs(args.rounds, args.output)
            print(json.dumps({"output": str(args.output), **result}, ensure_ascii=False, indent=2))
        elif args.command == "freeze":
            output = freeze_directory(
                source=args.source,
                output=args.output,
                dataset_id=args.dataset_id,
                ground_truth=args.ground_truth,
                source_session_id=args.source_session_id,
            )
            print(output)
        elif args.command == "transform":
            print(transform_dataset(dataset_path=args.dataset, spec_path=args.spec, output=args.output))
        elif args.command == "capture":
            print(
                capture_frames(
                    output=args.output,
                    dataset_id=args.dataset_id,
                    count=args.count,
                    command=args.command,
                    interval_s=args.interval,
                    ground_truth=args.ground_truth,
                    source_session_id=args.source_session_id,
                    width=args.width,
                    height=args.height,
                )
            )
        elif args.command == "probe":
            result = probe_server(
                server_url=args.server_url,
                image_path=args.image,
                output_path=args.output,
                system_prompt=args.system_prompt,
                question=args.question,
                timeout_s=args.timeout,
            )
            print(json.dumps(result, ensure_ascii=False, indent=2))
        else:
            raise AssertionError(args.command)
    except (OSError, ValueError, RuntimeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    return 0
