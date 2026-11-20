"""Robustness analyses for the paper.

This script treats the semantic seed, rather than each surface realization,
as the resampling unit. It also reports simple escalation baselines,
controller feature ablations, cross-task threshold transfer, and a lexical
stress test for the transparent detectors.

Usage: python reproduce/audit_analysis.py <combined_run_dir>
"""
import ast
import itertools
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.stats import wilcoxon

sys.path.insert(0, str(Path(__file__).parent))
from _paths import DATA_DIR, ROOT  # noqa: E402  (also puts the package dir on sys.path)
import controller as ctl  # noqa: E402
from detectors import detect  # noqa: E402


RNG_SEED = 1701
N_BOOT = 5000
FEATURES = ("U", "C", "M", "H")
WEIGHT_GRID = (0.0, 0.25, 0.5, 0.75, 1.0)
TAU_GRID = tuple(round(0.2 + 0.15 * i, 2) for i in range(9))


def correct_array(d, actions=None):
    actions = d.action.to_numpy(object) if actions is None else np.asarray(actions, object)
    return np.asarray([a in set(acc) for a, acc in zip(actions, d.acceptable)], bool)


def metrics(d, actions=None):
    actions = d.action.to_numpy(object) if actions is None else np.asarray(actions, object)
    req = d.esc_required.to_numpy(bool)
    esc = actions == "ESCALATE"
    correct = correct_array(d, actions)
    return {
        "n": int(len(d)),
        "n_seeds": int(d.seed_id.nunique()),
        "decision_accuracy": float(correct.mean()),
        "esc_sensitivity": float(esc[req].mean()) if req.any() else np.nan,
        "esc_specificity": float((~esc[~req]).mean()) if (~req).any() else np.nan,
        "missed_escalation_rate": float((~esc[req]).mean()) if req.any() else np.nan,
        "utility_5:1": float(ctl.utility(actions, req, c_fn=5.0)),
        "utility_10:1": float(ctl.utility(actions, req, c_fn=10.0)),
    }


def cluster_bootstrap_ci(d, metric_name, n_boot=N_BOOT):
    """Percentile CI resampling complete semantic seeds with replacement."""
    rows = []
    for _, group in d.groupby("seed_id"):
        actions = group.action.to_numpy(object)
        req = group.esc_required.to_numpy(bool)
        esc = actions == "ESCALATE"
        correct = correct_array(group)
        rows.append({
            "n": len(group),
            "correct": int(correct.sum()),
            "required": int(req.sum()),
            "tp": int((esc & req).sum()),
            "tn": int((~esc & ~req).sum()),
            "fn": int((~esc & req).sum()),
            "fp": int((esc & ~req).sum()),
        })
    counts = pd.DataFrame(rows).to_numpy(float)
    rng = np.random.default_rng(RNG_SEED)
    draws = rng.integers(0, len(counts), size=(n_boot, len(counts)))
    sampled = counts[draws].sum(axis=1)
    n, correct, required, tp, tn, fn, fp = sampled.T
    values = {
        "decision_accuracy": correct / n,
        "esc_sensitivity": tp / required,
        "missed_escalation_rate": fn / required,
        "utility_5:1": (tp + tn - 5.0 * fn - fp) / n,
    }[metric_name]
    return [float(np.nanpercentile(values, 2.5)), float(np.nanpercentile(values, 97.5))]


def tune_restricted(dev, allowed):
    """Tune the published policy while restricting which inputs may be used."""
    allowed = set(allowed)
    base = dev.action.to_numpy(object)
    req = dev.esc_required.to_numpy(bool)
    acceptable = [set(x) for x in dev.acceptable]
    arrays = {
        "U": 1.0 - dev.confidence.to_numpy(float),
        "C": dev.C.to_numpy(float),
        "M": dev.M.to_numpy(float),
        "H": dev.H.to_numpy(float),
    }
    grids = [WEIGHT_GRID if f in allowed else (0.0,) for f in FEATURES]
    best = None
    for w in itertools.product(*grids):
        if sum(w) == 0:
            continue
        risk = sum(weight * arrays[f] for weight, f in zip(w, FEATURES))
        for tau_low, tau_high in itertools.combinations(TAU_GRID, 2):
            actions = ctl.apply_policy(base, risk, tau_low, tau_high)
            utility = ctl.utility(actions, req, c_fn=5.0)
            accuracy = ctl.decision_accuracy(actions, acceptable)
            key = (utility, accuracy, tuple(-x for x in w), -tau_low, -tau_high)
            if best is None or key > best["key"]:
                best = {
                    "key": key,
                    "weights": dict(zip(FEATURES, map(float, w))),
                    "tau_low": float(tau_low),
                    "tau_high": float(tau_high),
                    "dev_utility_5:1": float(utility),
                    "dev_decision_accuracy": float(accuracy),
                }
    best.pop("key")
    return best


def apply_tuned(d, params):
    risk = sum(
        params["weights"][f]
        * ((1.0 - d.confidence.to_numpy(float)) if f == "U" else d[f].to_numpy(float))
        for f in FEATURES
    )
    return ctl.apply_policy(
        d.action.to_numpy(object), risk, params["tau_low"], params["tau_high"]
    )


def seed_clustered_main(test):
    rows = []
    for (model, condition), group in test.groupby(["model", "condition"]):
        row = {"model": model, "condition": condition, **metrics(group)}
        for name in ("decision_accuracy", "esc_sensitivity", "missed_escalation_rate", "utility_5:1"):
            row[name + "_seed_clustered_ci"] = cluster_bootstrap_ci(group, name)
        rows.append(row)
    return rows


def policy_comparisons(base):
    rows = []
    specs = {
        "confidence_only": ("U",),
        "workflow_only": ("C", "M", "H"),
        "full": FEATURES,
        "risk_cue_only": ("H",),
    }
    for model, group in base.groupby("model"):
        dev = group[group.split == "dev"].dropna(subset=["action", "confidence"])
        test = group[group.split == "test"].dropna(subset=["action", "confidence"])
        rows.append({"model": model, "policy": "base_uncertainty_prompt", **metrics(test)})
        for name, allowed in specs.items():
            params = tune_restricted(dev, allowed)
            actions = apply_tuned(test, params)
            rows.append({"model": model, "policy": name, **metrics(test, actions), **params})
        for name, action in (("always_escalate", "ESCALATE"), ("never_escalate", "ANSWER")):
            actions = np.repeat(action, len(test))
            rows.append({"model": model, "policy": name, **metrics(test, actions)})
    return rows


def cross_task_transfer(base):
    rows = []
    for model, group in base.groupby("model"):
        for task in sorted(group.task.unique()):
            dev = group[(group.split == "dev") & (group.task != task)].dropna(subset=["action", "confidence"])
            test = group[(group.split == "test") & (group.task == task)].dropna(subset=["action", "confidence"])
            params = tune_restricted(dev, FEATURES)
            actions = apply_tuned(test, params)
            rows.append({"model": model, "held_out_task": task, **metrics(test, actions), **params})
    return rows


def paired_seed_effects(test):
    rows = []
    work = test.copy()
    work["correct"] = correct_array(work).astype(float)
    for (model, condition), group in work[work.condition.isin(["vanilla", "uncertainty"])].groupby(["model", "condition"]):
        seed_variant = group.groupby(["seed_id", "perturbation"], as_index=False).correct.mean()
        wide = seed_variant.pivot(index="seed_id", columns="perturbation", values="correct")
        for perturbation in ("missing", "stale", "conflict", "late_risk"):
            paired = wide[["clean", perturbation]].dropna()
            delta = paired[perturbation] - paired["clean"]
            rng = np.random.default_rng(RNG_SEED)
            boot = []
            arr = delta.to_numpy(float)
            for _ in range(N_BOOT):
                boot.append(float(rng.choice(arr, size=len(arr), replace=True).mean()))
            try:
                if np.allclose(arr, 0):
                    raise ValueError("all paired differences are zero")
                p_value = float(wilcoxon(arr, zero_method="pratt", alternative="two-sided").pvalue)
            except ValueError:
                p_value = 1.0
            rows.append({
                "model": model,
                "condition": condition,
                "perturbation": perturbation,
                "n_semantic_seeds": int(len(arr)),
                "clean_accuracy": float(paired.clean.mean()),
                "perturbed_accuracy": float(paired[perturbation].mean()),
                "paired_delta": float(arr.mean()),
                "paired_delta_seed_bootstrap_ci": [float(np.percentile(boot, 2.5)), float(np.percentile(boot, 97.5))],
                "wilcoxon_p": p_value,
            })
    # Holm family-wise correction across the 20 model-by-perturbation tests
    # within each prompting condition.
    for condition in ("vanilla", "uncertainty"):
        indices = [i for i, row in enumerate(rows) if row["condition"] == condition]
        ordered = sorted(indices, key=lambda i: rows[i]["wilcoxon_p"])
        running = 0.0
        for rank, index in enumerate(ordered):
            adjusted = min(1.0, (len(ordered) - rank) * rows[index]["wilcoxon_p"])
            running = max(running, adjusted)
            rows[index]["wilcoxon_holm_p"] = float(running)
    return rows


def detector_stress(root):
    path = DATA_DIR / "detector_stress.jsonl"
    items = [json.loads(line) for line in open(path, encoding="utf-8")]
    rows = []
    for item in items:
        detector = item["detector"]
        rows.append({
            **item,
            "in_domain_detected": int(detect(item["in_domain"])[detector]),
            "oov_detected": int(detect(item["oov"])[detector]),
        })
    frame = pd.DataFrame(rows)
    summary = []
    for detector, group in frame.groupby("detector"):
        summary.append({
            "detector": detector,
            "n_concepts": int(len(group)),
            "in_domain_recall": float(group.in_domain_detected.mean()),
            "oov_paraphrase_recall": float(group.oov_detected.mean()),
        })
    return rows, summary


def main():
    run_dir = Path(sys.argv[1]).resolve()
    root = ROOT
    metrics_dir = run_dir / "metrics"
    frame = pd.read_csv(
        metrics_dir / "predictions_long.csv",
        converters={"acceptable": lambda value: tuple(ast.literal_eval(value))},
    )
    # The controller rows are retained for clustered CIs; policy re-tuning starts
    # from the uncertainty-prompted model outputs only.
    test = frame[frame.split == "test"].copy()
    base = frame[frame.condition == "uncertainty"].copy()

    clustered = seed_clustered_main(test)
    policies = policy_comparisons(base)
    transfer = cross_task_transfer(base)
    paired = paired_seed_effects(test)
    stress_rows, stress_summary = detector_stress(root)

    outputs = {
        "seed_clustered_main.json": clustered,
        "policy_comparisons.json": policies,
        "cross_task_transfer.json": transfer,
        "paired_seed_effects.json": paired,
        "detector_stress_details.json": stress_rows,
        "detector_stress_summary.json": stress_summary,
    }
    for name, obj in outputs.items():
        with open(metrics_dir / name, "w", encoding="utf-8") as handle:
            json.dump(obj, handle, indent=2)
    for name, obj in (
        ("seed_clustered_main.csv", clustered),
        ("policy_comparisons.csv", policies),
        ("cross_task_transfer.csv", transfer),
        ("paired_seed_effects.csv", paired),
        ("detector_stress_details.csv", stress_rows),
        ("detector_stress_summary.csv", stress_summary),
    ):
        pd.json_normalize(obj).to_csv(metrics_dir / name, index=False)
    print("audit metrics written to", metrics_dir)


if __name__ == "__main__":
    main()
