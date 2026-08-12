from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from typing import Any, Mapping

from .config import load_dataset
from .schema import sha256_bytes
from .storage import atomic_write_json


IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp"}


def freeze_directory(
    *,
    source: Path,
    output: Path,
    dataset_id: str,
    ground_truth: str | None,
    source_session_id: str | None,
) -> Path:
    source = source.resolve()
    output = output.resolve()
    if output.exists():
        raise FileExistsError(f"dataset output already exists: {output}")
    if ground_truth not in (None, "yes", "no"):
        raise ValueError("ground_truth must be yes, no, or omitted")
    files = sorted(
        path for path in source.iterdir() if path.is_file() and path.suffix.lower() in IMAGE_SUFFIXES
    )
    if not files:
        raise ValueError(f"no supported images found in {source}")
    frames_dir = output / "frames"
    frames_dir.mkdir(parents=True)
    frames: list[dict[str, Any]] = []
    seen_hashes: set[str] = set()
    for index, path in enumerate(files, start=1):
        data = path.read_bytes()
        digest = sha256_bytes(data)
        if digest in seen_hashes:
            raise ValueError(f"duplicate image bytes detected: {path}")
        seen_hashes.add(digest)
        suffix = ".jpg" if path.suffix.lower() == ".jpeg" else path.suffix.lower()
        frame_id = f"f{index:04d}_{digest[:12]}"
        target = frames_dir / f"{frame_id}{suffix}"
        shutil.copyfile(path, target)
        frames.append(
            {
                "frame_id": frame_id,
                "path": target.relative_to(output).as_posix(),
                "ground_truth": ground_truth,
                "source_session_id": source_session_id,
                "sha256": digest,
                "bytes": len(data),
                "metadata": {"source_name": path.name},
            }
        )
    manifest = {
        "schema_version": 1,
        "dataset_id": dataset_id,
        "frames": frames,
    }
    manifest_path = output / "dataset.json"
    atomic_write_json(manifest_path, manifest)
    return manifest_path


def transform_dataset(*, dataset_path: Path, spec_path: Path, output: Path) -> Path:
    dataset = load_dataset(dataset_path)
    spec = _read_spec(spec_path)
    output = output.resolve()
    if output.exists():
        raise FileExistsError(f"transform output already exists: {output}")
    frames_dir = output / "frames"
    frames_dir.mkdir(parents=True)
    output_frames: list[dict[str, Any]] = []
    try:
        for frame in dataset.frames:
            for profile in spec["profiles"]:
                profile_id = profile["id"]
                suffix = profile.get("suffix", ".jpg")
                if not isinstance(suffix, str) or not suffix.startswith("."):
                    raise ValueError(f"profile {profile_id}: suffix must start with a dot")
                target = frames_dir / f"{frame.frame_id}__{profile_id}{suffix}"
                _apply_profile(frame.path, target, profile)
                data = target.read_bytes()
                output_frames.append(
                    {
                        "frame_id": f"{frame.frame_id}__{profile_id}",
                        "path": target.relative_to(output).as_posix(),
                        "ground_truth": frame.ground_truth,
                        "source_session_id": frame.source_session_id,
                        "source_width": frame.source_width,
                        "source_height": frame.source_height,
                        "sha256": sha256_bytes(data),
                        "bytes": len(data),
                        "metadata": {
                            **dict(frame.metadata),
                            "source_frame_id": frame.frame_id,
                            "transform_id": profile_id,
                            "transform": profile,
                        },
                    }
                )
    except BaseException:
        shutil.rmtree(output)
        raise
    manifest_path = output / "dataset.json"
    atomic_write_json(
        manifest_path,
        {
            "schema_version": 1,
            "dataset_id": str(spec.get("dataset_id") or f"{dataset.dataset_id}_transformed"),
            "source_dataset": str(dataset.manifest_path),
            "transform_spec": str(spec_path.resolve()),
            "frames": output_frames,
        },
    )
    return manifest_path


def _read_spec(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"cannot read transform spec {path}: {exc}") from exc
    if not isinstance(value, dict) or not isinstance(value.get("profiles"), list):
        raise ValueError("transform spec must contain a profiles list")
    seen: set[str] = set()
    for profile in value["profiles"]:
        if not isinstance(profile, dict) or not isinstance(profile.get("id"), str):
            raise ValueError("each transform profile needs a string id")
        if profile["id"] in seen:
            raise ValueError(f"duplicate transform profile id: {profile['id']}")
        seen.add(profile["id"])
        if profile.get("kind") not in ("copy", "pillow-reencode", "pillow-blur", "pillow-resize", "command"):
            raise ValueError(f"unsupported transform kind: {profile.get('kind')!r}")
    return value


def _apply_profile(source: Path, target: Path, profile: Mapping[str, Any]) -> None:
    kind = profile["kind"]
    if kind == "copy":
        shutil.copyfile(source, target)
        return
    if kind == "command":
        command = profile.get("command")
        if not isinstance(command, list) or not command or not all(isinstance(arg, str) for arg in command):
            raise ValueError(f"profile {profile['id']}: command must be a non-empty string list")
        argv = [arg.replace("{input}", str(source)).replace("{output}", str(target)) for arg in command]
        subprocess.run(argv, check=True, timeout=float(profile.get("timeout_s", 120)))
        if not target.is_file() or target.stat().st_size == 0:
            raise RuntimeError(f"profile {profile['id']} did not create {target}")
        return

    try:
        from PIL import Image, ImageFilter
    except ImportError as exc:
        raise RuntimeError("Pillow transforms require: python -m pip install -e .[image]") from exc
    with Image.open(source) as image:
        image.load()
        if kind == "pillow-blur":
            sigma = float(profile.get("sigma", 1.0))
            if sigma < 0:
                raise ValueError("blur sigma cannot be negative")
            image = image.filter(ImageFilter.GaussianBlur(radius=sigma))
        elif kind == "pillow-resize":
            width = int(profile["width"])
            height = int(profile["height"])
            resampling_name = str(profile.get("resampling", "LANCZOS")).upper()
            try:
                resampling = getattr(Image.Resampling, resampling_name)
            except AttributeError as exc:
                raise ValueError(f"unknown resampling mode: {resampling_name}") from exc
            image = image.resize((width, height), resampling)
        save_options: dict[str, Any] = {}
        if target.suffix.lower() in (".jpg", ".jpeg"):
            if image.mode not in ("RGB", "L"):
                image = image.convert("RGB")
            save_options["quality"] = int(profile.get("quality", 95))
            save_options["subsampling"] = int(profile.get("subsampling", 0))
        image.save(target, **save_options)
