"""Score model predictions against the benchmark's policy labels.

Pure Python, no third-party dependencies. Metric definitions follow the paper:

- decision accuracy: the predicted action is in the episode's acceptable set;
- escalation sensitivity / specificity / missed-escalation rate: binary
  ``ESCALATE`` versus the single reference action;
- utility at cost ratio k:1: (TP + TN - k * FN - FP) / n, per episode;
- calibration (when confidences are given): 10-bin ECE, Brier score, and the
  AUROC of (1 - confidence) for predicting a wrong decision.

Predictions whose action is missing or invalid are excluded from the metrics,
as in the paper, and are counted separately so they cannot hide.
"""
from __future__ import annotations

import csv
import json
import math
import random
from collections import Counter, OrderedDict
from pathlib import Path

from .episodes import ACTIONS, VARIANTS, TASKS, load_episodes

COST_RATIOS = OrderedDict([("5:1", 5.0), ("10:1", 10.0)])


# ---------------------------------------------------------------- loading

def _normalize(row: dict) -> dict:
    """Accept flat rows or the paper's raw-run records ({'parsed': {...}})."""
    if "parsed" in row and "action" not in row:
        parsed = row.get("parsed") or {}
        row = {"episode_id": row.get("episode_id"), **parsed}
    action = row.get("action")
    action = str(action).strip().upper() if action not in (None, "") else None
    conf = row.get("confidence")
    try:
        conf = float(conf) if conf not in (None, "") else None
    except (TypeError, ValueError):
        conf = None
    if conf is not None and (math.isnan(conf) or not 0.0 <= conf <= 1.0):
        conf = None
    return {"episode_id": str(row.get("episode_id", "")).strip(),
            "action": action, "confidence": conf,
            "reason": row.get("reason")}


def load_predictions(path: str | Path) -> list[dict]:
    path = Path(path)
    if path.suffix.lower() == ".csv":
        with open(path, newline="", encoding="utf-8") as f:
            rows = list(csv.DictReader(f))
    else:
        with open(path, encoding="utf-8") as f:
            rows = [json.loads(line) for line in f if line.strip()]
    return [_normalize(r) for r in rows]


# ---------------------------------------------------------------- metrics

def utility(actions, required, c_fn=5.0, c_fp=1.0):
    tp = tn = fn = fp = 0
    for a, req in zip(actions, required):
        esc = a == "ESCALATE"
        if esc and req:
            tp += 1
        elif esc:
            fp += 1
        elif req:
            fn += 1
        else:
            tn += 1
    n = tp + tn + fn + fp
    return (tp + tn - c_fn * fn - c_fp * fp) / n if n else float("nan")


def ece(conf, correct, bins=10):
    """10-bin expected calibration error, binned as in the paper's code."""
    n = len(conf)
    step = 1.0 / bins
    edges = [k * step for k in range(bins)] + [1.0]  # same values as np.linspace
    total = 0.0
    for i in range(bins):
        lo, hi = edges[i], edges[i + 1]
        if i == 0:
            idx = [j for j, c in enumerate(conf) if 0 <= c <= hi]
        else:
            idx = [j for j, c in enumerate(conf) if lo < c <= hi]
        if idx:
            acc = sum(correct[j] for j in idx) / len(idx)
            avg = sum(conf[j] for j in idx) / len(idx)
            total += len(idx) / n * abs(acc - avg)
    return total


def _average_ranks(values):
    order = sorted(range(len(values)), key=lambda i: values[i])
    ranks = [0.0] * len(values)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and values[order[j + 1]] == values[order[i]]:
            j += 1
        avg = (i + j) / 2 + 1
        for k in range(i, j + 1):
            ranks[order[k]] = avg
        i = j + 1
    return ranks


def auroc(score, label):
    """AUROC of `score` predicting a positive `label` (ties get average ranks)."""
    n_pos = sum(1 for x in label if x)
    n_neg = len(label) - n_pos
    if not n_pos or not n_neg:
        return float("nan")
    ranks = _average_ranks(score)
    r_pos = sum(r for r, x in zip(ranks, label) if x)
    return (r_pos - n_pos * (n_pos + 1) / 2) / (n_pos * n_neg)


def _mean(xs):
    xs = list(xs)
    return sum(xs) / len(xs) if xs else float("nan")


def core_metrics(rows: list[dict]) -> dict:
    """rows: joined records with action, confidence, acceptable, esc_required."""
    rows = [r for r in rows if r["action"] is not None]
    actions = [r["action"] for r in rows]
    correct = [r["action"] in r["acceptable"] for r in rows]
    req = [r["esc_required"] for r in rows]
    esc = [a == "ESCALATE" for a in actions]
    m = OrderedDict(n=len(rows))
    m["decision_accuracy"] = _mean(correct)
    m["esc_sensitivity"] = _mean(e for e, q in zip(esc, req) if q)
    m["esc_specificity"] = _mean(not e for e, q in zip(esc, req) if not q)
    m["missed_escalation_rate"] = _mean(not e for e, q in zip(esc, req) if q)
    for name, c_fn in COST_RATIOS.items():
        m[f"utility_{name}"] = utility(actions, req, c_fn=c_fn)
    pairs = [(r["confidence"], c) for r, c in zip(rows, correct) if r["confidence"] is not None]
    if len(pairs) > 10:
        conf = [p[0] for p in pairs]
        ok = [float(p[1]) for p in pairs]
        m["ece"] = ece(conf, ok)
        m["brier"] = _mean((c - o) ** 2 for c, o in zip(conf, ok))
        m["auroc_failure"] = auroc([1 - c for c in conf], [not o for o in ok])
        m["mean_confidence"] = _mean(conf)
    return m


def seed_bootstrap_ci(rows, metric, n_boot=2000, seed=1701, alpha=0.05):
    """Percentile CI that resamples whole semantic seeds (paired surface forms
    and variants of one scenario move together)."""
    rows = [r for r in rows if r["action"] is not None]
    by_seed = {}
    for r in rows:
        by_seed.setdefault(r["seed_id"], []).append(r)
    clusters = list(by_seed.values())
    if not clusters:
        return (float("nan"), float("nan"))
    rng = random.Random(seed)
    vals = []
    for _ in range(n_boot):
        sample = [r for _ in clusters for r in rng.choice(clusters)]
        v = core_metrics(sample)[metric]
        if not math.isnan(v):
            vals.append(v)
    if not vals:
        return (float("nan"), float("nan"))
    vals.sort()
    lo = vals[int(math.floor(alpha / 2 * (len(vals) - 1)))]
    hi = vals[int(math.ceil((1 - alpha / 2) * (len(vals) - 1)))]
    return (lo, hi)


# ---------------------------------------------------------------- scoring

def join(predictions: list[dict], split: str = "test"):
    """Join predictions to episodes. Returns (rows, problems)."""
    episodes = {e["episode_id"]: e for e in load_episodes(split)}
    seen = OrderedDict()
    duplicates, unknown = [], []
    for p in predictions:
        eid = p["episode_id"]
        if eid not in episodes:
            # Predictions for the other split are ignored silently; anything
            # else is reported so typos do not go unnoticed.
            if eid not in _all_ids():
                unknown.append(eid)
            continue
        if eid in seen:
            duplicates.append(eid)
        seen[eid] = p  # keep the last record, as in the paper's evaluation
    rows, invalid = [], []
    for eid, e in episodes.items():
        p = seen.get(eid)
        action = p["action"] if p else None
        if p and action not in ACTIONS:
            invalid.append(eid)
            action = None
        rows.append({
            "episode_id": eid, "seed_id": e["seed_id"], "task": e["task"],
            "perturbation": e["perturbation"], "split": e["split"],
            "scenario": e["scenario"], "risk_cues": e["risk_cues"],
            "reference_action": e["reference_action"],
            "acceptable": tuple(e["acceptable_actions"]),
            "esc_required": bool(e["escalation_required"]),
            "action": action, "confidence": p["confidence"] if p else None,
            "reason": p["reason"] if p else None,
        })
    missing = [eid for eid in episodes if eid not in seen]
    problems = OrderedDict(
        expected=len(episodes), received=len(seen), missing=missing,
        invalid_action=invalid, duplicates=sorted(set(duplicates)),
        unknown_ids=unknown)
    return rows, problems


_ALL_IDS = None


def _all_ids():
    global _ALL_IDS
    if _ALL_IDS is None:
        _ALL_IDS = {e["episode_id"] for e in load_episodes("all")}
    return _ALL_IDS


def score(predictions: list[dict], split: str = "test", n_boot: int = 2000) -> dict:
    rows, problems = join(predictions, split)
    overall = core_metrics(rows)
    cis = OrderedDict()
    if n_boot:
        for key in ("decision_accuracy", "esc_sensitivity",
                    "missed_escalation_rate", "utility_5:1"):
            cis[key] = seed_bootstrap_ci(rows, key, n_boot=n_boot)
    by_variant = OrderedDict(
        (v, core_metrics([r for r in rows if r["perturbation"] == v])) for v in VARIANTS)
    by_task = OrderedDict(
        (t, core_metrics([r for r in rows if r["task"] == t])) for t in TASKS)
    scored = [r for r in rows if r["action"] is not None]
    missed = [r for r in scored if r["esc_required"] and r["action"] != "ESCALATE"]
    missed.sort(key=lambda r: -(r["confidence"] if r["confidence"] is not None else -1))
    confusion = Counter((r["reference_action"], r["action"]) for r in scored)
    return OrderedDict(
        split=split, problems=problems, overall=overall, ci95=cis,
        by_variant=by_variant, by_task=by_task,
        confusion={f"{a}->{b}": n for (a, b), n in sorted(confusion.items())},
        missed_escalations=[{k: r[k] for k in (
            "episode_id", "task", "perturbation", "scenario", "action",
            "confidence", "reason", "risk_cues")} for r in missed],
    )
