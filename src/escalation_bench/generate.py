"""Rebuild the benchmark from its hand-authored seeds.

Every episode is assembled programmatically from one seed, one surface
parameterization, and one of five variants. No language model is used.
Each episode records a content hash, and the dataset file hash is stored in
``data/dataset_manifest.json``.

``build_episodes()`` returns the episodes in memory. ``write_dataset()`` writes
them to a directory. ``escalation-bench verify-data`` uses both to confirm
that the bundled ``episodes.jsonl`` is byte-for-byte reproducible.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from .seeds import doc_update, evidence, messaging, triage
from .seeds.common import VARIANTS

ALL_SEEDS = doc_update.SEEDS + evidence.SEEDS + messaging.SEEDS + triage.SEEDS

# Seeds whose numeric suffix is 01 or 02 form the development split
# (controller threshold tuning); the rest are the test split.
DEV_SEED_SUFFIXES = ("_01", "_02")


def fmt(text, p):
    return text.format(**p) if text else text


def render_episode(s, p, pi, variant):
    """Assemble the episode transcript blocks for one variant."""
    blocks = []
    blocks.append(("SETTING", fmt(s["setting"], p)))
    blocks.append(("EARLIER RECORD", fmt(s["baseline"], p)))

    if variant == "clean":
        blocks.append(("NEW INFORMATION", fmt(s["update_full"], p)))
        blocks.append(("REQUEST", fmt(s["request"], p)))
    elif variant == "missing":
        blocks.append(("NEW INFORMATION", fmt(s["update_no_critical"], p)))
        blocks.append(("REQUEST", fmt(s["request"], p)))
    elif variant == "stale":
        blocks.append(("NEW INFORMATION", fmt(s["update_full"], p)))
        blocks.append(("AUTO-GENERATED CHART SUMMARY (compiled earlier, may not reflect "
                       "recent updates)",
                       fmt(s["stale_fact"], p) + " " + fmt(s["distractor"], p)))
        blocks.append(("REQUEST", fmt(s["request"], p)))
    elif variant == "conflict":
        blocks.append(("NEW INFORMATION", fmt(s["update_full"], p)))
        blocks.append(("ADDITIONAL INFORMATION", fmt(s["conflict_addon"], p)))
        blocks.append(("REQUEST", fmt(s["request"], p)))
    elif variant == "late_risk":
        blocks.append(("NEW INFORMATION",
                       fmt(s["update_no_critical"], p) + " " + fmt(s["distractor"], p)))
        blocks.append(("REQUEST", fmt(s["request"], p)))
        blocks.append(("MESSAGE RECEIVED AFTER THE REQUEST WAS SUBMITTED",
                       fmt(s["late_risk_cue"], p)))
    else:
        raise ValueError(variant)

    transcript = "\n\n".join(f"[{h}]\n{t}" for h, t in blocks)
    ref, acceptable = s["refs"][variant]
    split = "dev" if s["seed_id"].endswith(DEV_SEED_SUFFIXES) else "test"
    ep = {
        "episode_id": f"{s['seed_id']}_p{pi}_{variant}",
        "task": s["task"],
        "seed_id": s["seed_id"],
        "param_index": pi,
        "perturbation": variant,
        "split": split,
        "severity": s["severity"],
        "scenario": s["scenario"],
        "transcript": transcript,
        "reference_action": ref,
        "acceptable_actions": acceptable,
        "escalation_required": ref == "ESCALATE",
        "required_facts": [fmt(x, p) for x in s["required_facts"]],
        "risk_cues": [fmt(x, p) for x in s["risk_cues"]],
        "rationale": s["rationale"],
    }
    ep["content_sha256"] = hashlib.sha256(
        json.dumps(ep, sort_keys=True).encode()).hexdigest()[:16]
    return ep


def build_episodes():
    episodes = []
    for s in ALL_SEEDS:
        for pi, p in enumerate(s["params"]):
            for v in VARIANTS:
                episodes.append(render_episode(s, p, pi, v))
    ids = [e["episode_id"] for e in episodes]
    assert len(ids) == len(set(ids)), "duplicate episode ids"
    return episodes


def episodes_bytes(episodes) -> bytes:
    """Serialize exactly as the original generator wrote episodes.jsonl."""
    return "".join(json.dumps(e) + "\n" for e in episodes).encode()


def write_dataset(out_dir: Path) -> dict:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    episodes = build_episodes()
    with open(out_dir / "seeds.jsonl", "w") as f:
        for s in ALL_SEEDS:
            f.write(json.dumps(s) + "\n")
    (out_dir / "episodes.jsonl").write_bytes(episodes_bytes(episodes))

    counts, ref_counts = {}, {}
    for e in episodes:
        counts[e["task"]] = counts.get(e["task"], 0) + 1
        key = f"{e['perturbation']}:{e['reference_action']}"
        ref_counts[key] = ref_counts.get(key, 0) + 1
    manifest = {
        "n_seeds": len(ALL_SEEDS),
        "n_episodes": len(episodes),
        "episodes_per_task": counts,
        "reference_actions_by_variant": dict(sorted(ref_counts.items())),
        "n_dev": sum(1 for e in episodes if e["split"] == "dev"),
        "n_test": sum(1 for e in episodes if e["split"] == "test"),
        "n_escalation_required": sum(1 for e in episodes if e["escalation_required"]),
        "dataset_sha256": hashlib.sha256(episodes_bytes(episodes)).hexdigest(),
        "generator": "programmatic assembly from hand-authored seeds (no LLM generation)",
    }
    with open(out_dir / "dataset_manifest.json", "w") as f:
        json.dump(manifest, f, indent=2)
    return manifest
