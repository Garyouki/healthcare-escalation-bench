"""Evaluate a completed run: metrics, controller, calibration, risk-coverage,
paired statistics. Writes everything under <run_dir>/metrics/.

Usage: python reproduce/evaluate.py <run_dir>
"""
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.stats import binomtest

sys.path.insert(0, str(Path(__file__).parent))
from _paths import DATA_DIR, ROOT  # noqa: E402  (also puts the package dir on sys.path)
from detectors import detect  # noqa: E402
import controller as ctl  # noqa: E402

RNG = np.random.default_rng(17)
N_BOOT = 100  # quick run summary; audit_analysis.py produces 5,000-draw CIs
COST_RATIOS = {"5:1": 5.0, "10:1": 10.0}


# ---------- loading ----------

def load_run(run_dir, episodes_path):
    eps = {e["episode_id"]: e for e in
           (json.loads(l) for l in open(episodes_path))}
    det = {eid: detect(e["transcript"]) for eid, e in eps.items()}
    rows = []
    for f in sorted((run_dir / "raw").glob("*.jsonl")):
        for line in open(f):
            r = json.loads(line)
            e = eps[r["episode_id"]]
            parsed = r.get("parsed")
            rows.append({
                "episode_id": r["episode_id"], "model": r["model"],
                "condition": r["condition"],
                "action": parsed["action"] if parsed else None,
                "confidence": parsed["confidence"] if parsed else np.nan,
                "reason": parsed["reason"] if parsed else None,
                "parse_ok": parsed is not None,
                "task": e["task"], "perturbation": e["perturbation"],
                "split": e["split"], "seed_id": e["seed_id"],
                "param_index": e["param_index"],
                "reference_action": e["reference_action"],
                "acceptable": tuple(e["acceptable_actions"]),
                "esc_required": e["escalation_required"],
                "severity": e["severity"],
                "H": det[r["episode_id"]]["H"],
                "C": det[r["episode_id"]]["C"],
                "M": det[r["episode_id"]]["M"],
            })
    df = pd.DataFrame(rows)
    # keep the last record per (episode, model, condition) in case of retries
    df = df.drop_duplicates(subset=["episode_id", "model", "condition"], keep="last")
    return df, eps


# ---------- controller ----------

def add_controller(df):
    out = []
    params = {}
    for model, g in df[df.condition == "uncertainty"].groupby("model"):
        g = g.dropna(subset=["action"])
        dev = g[g.split == "dev"]
        pack = lambda d: {
            "conf": d.confidence.to_numpy(float),
            "C": d.C.to_numpy(float), "M": d.M.to_numpy(float),
            "H": d.H.to_numpy(float),
            "base_action": d.action.to_numpy(object),
            "esc_required": d.esc_required.to_numpy(bool),
            "acceptable": [set(a) for a in d.acceptable],
        }
        best = ctl.tune(pack(dev))
        params[model] = best
        R = ctl.risk_scores(g.confidence.to_numpy(float), g.C.to_numpy(float),
                            g.M.to_numpy(float), g.H.to_numpy(float), best["w"])
        acts = ctl.apply_policy(g.action.to_numpy(object), R,
                                best["tau_low"], best["tau_high"])
        gc = g.copy()
        gc["condition"] = "controller"
        gc["action"] = acts
        gc["risk_score"] = R
        out.append(gc)
    return pd.concat([df] + out, ignore_index=True), params


# ---------- metrics ----------

def ece(conf, correct, bins=10):
    conf, correct = np.asarray(conf), np.asarray(correct, float)
    edges = np.linspace(0, 1, bins + 1)
    e = 0.0
    for i in range(bins):
        m = (conf > edges[i]) & (conf <= edges[i + 1]) if i else (conf >= 0) & (conf <= edges[1])
        if m.sum():
            e += m.mean() * abs(correct[m].mean() - conf[m].mean())
    return e


def auroc(score, label):
    """AUROC of `score` predicting binary `label` (1 = failure)."""
    score, label = np.asarray(score, float), np.asarray(label, bool)
    pos, neg = score[label], score[~label]
    if len(pos) == 0 or len(neg) == 0:
        return np.nan
    ranks = pd.Series(score).rank().to_numpy()
    return (ranks[label].sum() - len(pos) * (len(pos) + 1) / 2) / (len(pos) * len(neg))


def core_metrics(d):
    d = d.dropna(subset=["action"])
    correct = np.array([a in set(acc) for a, acc in zip(d.action, d.acceptable)])
    esc = (d.action == "ESCALATE").to_numpy()
    req = d.esc_required.to_numpy(bool)
    m = {
        "n": len(d),
        "decision_accuracy": float(correct.mean()) if len(d) else np.nan,
        "esc_sensitivity": float(esc[req].mean()) if req.sum() else np.nan,
        "esc_specificity": float((~esc[~req]).mean()) if (~req).sum() else np.nan,
        "missed_escalation_rate": float((~esc[req]).mean()) if req.sum() else np.nan,
    }
    for name, c_fn in COST_RATIOS.items():
        m[f"utility_{name}"] = float(ctl.utility(d.action.to_numpy(object), req, c_fn=c_fn))
    conf = d.confidence.to_numpy(float)
    ok = ~np.isnan(conf)
    if ok.sum() > 10:
        m["ece"] = float(ece(conf[ok], correct[ok]))
        m["brier"] = float(np.mean((conf[ok] - correct[ok].astype(float)) ** 2))
        m["auroc_failure"] = float(auroc(1 - conf[ok], ~correct[ok]))
        m["mean_confidence"] = float(conf[ok].mean())
    return m


def bootstrap_ci(d, metric_fn, n=N_BOOT, cluster_col="seed_id"):
    """Cluster bootstrap so paired surface forms share a resampling unit."""
    vals = []
    d = d.dropna(subset=["action"]).reset_index(drop=True)
    clusters = list(d[cluster_col].drop_duplicates())
    grouped = {cluster: d[d[cluster_col] == cluster] for cluster in clusters}
    for _ in range(n):
        sampled = RNG.choice(clusters, size=len(clusters), replace=True)
        pieces = []
        for draw, cluster in enumerate(sampled):
            piece = grouped[cluster].copy()
            piece["_bootstrap_cluster"] = draw
            pieces.append(piece)
        vals.append(metric_fn(pd.concat(pieces, ignore_index=True)))
    return float(np.nanpercentile(vals, 2.5)), float(np.nanpercentile(vals, 97.5))


# ---------- risk-coverage ----------

def risk_coverage(d, score):
    """Defer lowest-score episodes to human (counts as ESCALATE).
    Returns curve arrays over all thresholds."""
    d = d.dropna(subset=["action"]).reset_index(drop=True)
    order = np.argsort(-score)  # descending: most confident first
    esc = (d.action == "ESCALATE").to_numpy()[order]
    req = d.esc_required.to_numpy(bool)[order]
    correct = np.array([a in set(acc) for a, acc in zip(d.action, d.acceptable)])[order]
    n, n_req = len(d), req.sum()
    cov, missed, sel_risk = [], [], []
    for k in range(0, n + 1):
        c_req, c_esc, c_ok = req[:k], esc[:k], correct[:k]
        cov.append(k / n)
        missed.append(((~c_esc) & c_req).sum() / n_req if n_req else np.nan)
        sel_risk.append(1 - c_ok.mean() if k else 0.0)
    return {"coverage": cov, "missed_escalation": missed, "selective_risk": sel_risk}


# ---------- paired stats ----------

def mcnemar_pairs(d_model):
    """Clean vs each perturbation, paired on (seed_id, param_index)."""
    res = []
    d = d_model.dropna(subset=["action"])
    d = d.assign(correct=[a in set(acc) for a, acc in zip(d.action, d.acceptable)])
    base = d[d.perturbation == "clean"].set_index(["seed_id", "param_index"]).correct
    for pert in ["missing", "stale", "conflict", "late_risk"]:
        v = d[d.perturbation == pert].set_index(["seed_id", "param_index"]).correct
        joined = pd.concat([base, v], axis=1, keys=["clean", "pert"]).dropna()
        b = int((joined.clean & ~joined.pert).sum())   # clean right, pert wrong
        c = int((~joined.clean & joined.pert).sum())
        p = binomtest(b, b + c, 0.5).pvalue if (b + c) else 1.0
        res.append({"perturbation": pert, "n_pairs": len(joined),
                    "clean_correct": float(joined.clean.mean()),
                    "pert_correct": float(joined.pert.mean()),
                    "discordant_clean_only": b, "discordant_pert_only": c,
                    "mcnemar_p": float(p)})
    return res


# ---------- utility vs threshold ----------

def utility_sweep(d, thresholds=None):
    d = d.dropna(subset=["action"])
    thresholds = thresholds if thresholds is not None else np.linspace(0, 1, 41)
    conf = d.confidence.to_numpy(float)
    base = d.action.to_numpy(object)
    req = d.esc_required.to_numpy(bool)
    out = {"threshold": list(map(float, thresholds))}
    for name, c_fn in COST_RATIOS.items():
        us = []
        for t in thresholds:
            acts = base.copy()
            acts[conf < t] = "ESCALATE"
            us.append(float(ctl.utility(acts, req, c_fn=c_fn)))
        out[f"utility_{name}"] = us
    return out


# ---------- detector quality ----------

def detector_report(df):
    ep = df.drop_duplicates("episode_id")
    rep = {}
    for ind, gold_mask in [("C", ep.perturbation == "conflict"),
                           ("M", ep.perturbation == "missing"),
                           ("H", ep.esc_required)]:
        pred = ep[ind].astype(bool)
        gold = gold_mask.to_numpy()
        tp = (pred & gold).sum(); fp = (pred & ~gold).sum(); fn = (~pred & gold).sum()
        rep[ind] = {"precision": float(tp / (tp + fp)) if tp + fp else np.nan,
                    "recall": float(tp / (tp + fn)) if tp + fn else np.nan,
                    "fired_rate": float(pred.mean())}
    return rep


# ---------- main ----------

def main():
    run_dir = Path(sys.argv[1])
    root = ROOT
    mdir = run_dir / "metrics"
    mdir.mkdir(exist_ok=True)

    df, eps = load_run(run_dir, DATA_DIR / "episodes.jsonl")
    df, ctl_params = add_controller(df)
    test = df[df.split == "test"]

    parse_report = df.groupby(["model", "condition"]).parse_ok.mean().reset_index()
    parse_report.to_csv(mdir / "parse_rates.csv", index=False)

    # main table with bootstrap CIs on key metrics
    main_rows = []
    for (model, cond), g in test.groupby(["model", "condition"]):
        m = core_metrics(g)
        for key in ["decision_accuracy", "esc_sensitivity", "missed_escalation_rate",
                    "utility_5:1"]:
            fn = {"decision_accuracy":
                      lambda d: np.mean([a in set(acc) for a, acc in zip(d.action, d.acceptable)]),
                  "esc_sensitivity":
                      lambda d: (d[d.esc_required].action == "ESCALATE").mean(),
                  "missed_escalation_rate":
                      lambda d: (d[d.esc_required].action != "ESCALATE").mean(),
                  "utility_5:1":
                      lambda d: ctl.utility(d.action.to_numpy(object),
                                            d.esc_required.to_numpy(bool), c_fn=5.0)}[key]
            lo, hi = bootstrap_ci(g, fn)
            m[f"{key}_ci"] = [lo, hi]
        main_rows.append({"model": model, "condition": cond, **m})
    with open(mdir / "main_table.json", "w") as f:
        json.dump(main_rows, f, indent=2)
    pd.json_normalize(main_rows).to_csv(mdir / "main_table.csv", index=False)

    # per-variant and per-task breakdowns
    byv = []
    for (model, cond, pert), g in test.groupby(["model", "condition", "perturbation"]):
        byv.append({"model": model, "condition": cond, "perturbation": pert,
                    **core_metrics(g)})
    pd.json_normalize(byv).to_csv(mdir / "by_variant.csv", index=False)
    byt = []
    for (model, cond, task), g in test.groupby(["model", "condition", "task"]):
        byt.append({"model": model, "condition": cond, "task": task,
                    **core_metrics(g)})
    pd.json_normalize(byt).to_csv(mdir / "by_task.csv", index=False)

    # paired McNemar (uncertainty and vanilla)
    mcn = []
    for cond in ["vanilla", "uncertainty"]:
        for model, g in test[test.condition == cond].groupby("model"):
            for row in mcnemar_pairs(g):
                mcn.append({"model": model, "condition": cond, **row})
    pd.DataFrame(mcn).to_csv(mdir / "mcnemar.csv", index=False)

    # risk-coverage curves per model
    rc = {}
    for model in test.model.unique():
        rc[model] = {}
        for cond in ["vanilla", "uncertainty"]:
            g = test[(test.model == model) & (test.condition == cond)].dropna(subset=["action"])
            rc[model][cond] = risk_coverage(g, g.confidence.to_numpy(float))
        g = test[(test.model == model) & (test.condition == "controller")].dropna(subset=["action"])
        rc[model]["controller"] = risk_coverage(g, -g.risk_score.to_numpy(float))
    with open(mdir / "risk_coverage.json", "w") as f:
        json.dump(rc, f)

    # utility-vs-threshold sweeps (uncertainty condition) + controller point
    sweeps = {}
    for model, g in test[test.condition == "uncertainty"].groupby("model"):
        sweeps[model] = utility_sweep(g)
        gc = test[(test.condition == "controller") & (test.model == model)]
        sweeps[model]["controller_point"] = {
            name: float(ctl.utility(gc.dropna(subset=["action"]).action.to_numpy(object),
                                    gc.dropna(subset=["action"]).esc_required.to_numpy(bool),
                                    c_fn=c_fn))
            for name, c_fn in COST_RATIOS.items()}
    with open(mdir / "utility_sweeps.json", "w") as f:
        json.dump(sweeps, f)

    # detectors + controller params
    with open(mdir / "detector_report.json", "w") as f:
        json.dump(detector_report(df), f, indent=2)
    with open(mdir / "controller_params.json", "w") as f:
        json.dump({m: {**p, "w": list(p["w"])} for m, p in ctl_params.items()}, f, indent=2)

    # failure examples: high-confidence missed escalations (uncertainty condition)
    fails = test[(test.condition == "uncertainty") & test.esc_required &
                 (test.action != "ESCALATE")].nlargest(8, "confidence")
    ex = []
    for _, r in fails.iterrows():
        ex.append({"episode_id": r.episode_id, "model": r.model,
                   "perturbation": r.perturbation, "action": r.action,
                   "confidence": float(r.confidence), "reason": r.reason,
                   "reference": r.reference_action,
                   "scenario": eps[r.episode_id]["scenario"],
                   "risk_cues": eps[r.episode_id]["risk_cues"]})
    with open(mdir / "failure_examples.json", "w") as f:
        json.dump(ex, f, indent=2)

    # tidy long-form predictions for the record
    df.to_csv(mdir / "predictions_long.csv", index=False)
    print("metrics written to", mdir)


if __name__ == "__main__":
    main()
