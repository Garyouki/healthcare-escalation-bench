"""Load the bundled benchmark and export model inputs without labels."""
from __future__ import annotations

import hashlib
import json
from importlib import resources
from pathlib import Path

ACTIONS = ("ANSWER", "ASK_CLARIFICATION", "ABSTAIN", "ESCALATE")
VARIANTS = ("clean", "missing", "stale", "conflict", "late_risk")
TASKS = ("documentation_update", "evidence_retrieval", "patient_messaging", "triage_handoff")
SPLITS = ("dev", "test", "all")

# Fields a model may see. Everything else (reference actions, acceptable sets,
# risk cues, rationale, required facts, variant labels) stays with the scorer.
INPUT_FIELDS = ("episode_id", "task", "transcript")

USER_SUFFIX = "\n\nChoose your action now and respond with the JSON object only."


def data_dir() -> Path:
    return Path(str(resources.files("escalation_bench") / "data"))


def episodes_path() -> Path:
    return data_dir() / "episodes.jsonl"


def load_episodes(split: str = "all", path: Path | None = None) -> list[dict]:
    if split not in SPLITS:
        raise ValueError(f"split must be one of {SPLITS}, got {split!r}")
    path = Path(path) if path else episodes_path()
    with open(path, encoding="utf-8") as f:
        episodes = [json.loads(line) for line in f if line.strip()]
    if split != "all":
        episodes = [e for e in episodes if e["split"] == split]
    return episodes


def load_manifest() -> dict:
    with open(data_dir() / "dataset_manifest.json", encoding="utf-8") as f:
        return json.load(f)


def dataset_sha256(path: Path | None = None) -> str:
    return hashlib.sha256(Path(path or episodes_path()).read_bytes()).hexdigest()


def model_inputs(split: str = "test") -> list[dict]:
    """Episode inputs safe to send to a model: id, task, and transcript only."""
    return [{k: e[k] for k in INPUT_FIELDS} for e in load_episodes(split)]


def user_message(transcript: str) -> str:
    """The exact user turn used in the paper runs."""
    return transcript + USER_SUFFIX
