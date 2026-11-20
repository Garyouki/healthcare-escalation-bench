"""Generate paper figures from a run's metrics/ directory.

Usage: python reproduce/figures.py <run_dir>

Palette: validated 3-slot categorical (blue/orange/aqua, all-pairs safe) for
conditions; 4-slot (+yellow, adjacent-safe) for models; single-hue sequential
(Blues) for the heatmap. Contrast WARN slots relieved with legends + direct
labels everywhere.
"""
import json
import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

COND_COLORS = {"vanilla": "#2a78d6", "uncertainty": "#eb6834", "controller": "#1baf7a"}
COND_LABELS = {"vanilla": "Vanilla confidence", "uncertainty": "Uncertainty-prompted",
               "controller": "Workflow-aware controller"}
MODEL_COLORS = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#8b5fbf"]
VARIANTS = ["clean", "missing", "stale", "conflict", "late_risk"]
VARIANT_LABELS = ["Clean", "Missing", "Stale", "Conflict", "Late-risk"]

plt.rcParams.update({
    "figure.dpi": 300, "savefig.dpi": 300, "font.size": 9,
    "axes.spines.top": False, "axes.spines.right": False,
    "axes.grid": True, "grid.color": "#e6e4dd", "grid.linewidth": 0.6,
    "axes.axisbelow": True, "lines.linewidth": 2.0,
    "axes.edgecolor": "#6b6a63", "axes.labelcolor": "#1a1a19",
    "xtick.color": "#6b6a63", "ytick.color": "#6b6a63",
})


def fig_risk_coverage(rc, out):
    models = sorted(rc.keys())
    ncols = 3 if len(models) > 4 else 2
    nrows = int(np.ceil(len(models) / ncols))
    fig, axes = plt.subplots(nrows, ncols, figsize=(4 * ncols, 3.2 * nrows),
                             sharex=True, sharey=True, squeeze=False)
    for ax, model in zip(axes.flat, models):
        for cond in ["vanilla", "uncertainty", "controller"]:
            d = rc[model][cond]
            ax.plot(d["coverage"], d["missed_escalation"],
                    color=COND_COLORS[cond], label=COND_LABELS[cond])
        ax.set_title(model, fontsize=9.5)
        ax.set_xlim(0, 1); ax.set_ylim(bottom=0)
    for ax in axes.flat[len(models):]:
        ax.set_visible(False)
    for ax in axes[-1]:
        ax.set_xlabel("Coverage (fraction handled by agent)")
    for ax in axes[:, 0]:
        ax.set_ylabel("Missed-escalation risk")
    axes.flat[0].legend(frameon=False, fontsize=8, loc="upper left")
    fig.suptitle("Risk-coverage: missed escalations vs. autonomy (test split)",
                 fontsize=11)
    fig.tight_layout(rect=[0, 0, 1, 0.97])
    fig.savefig(out / "fig1_risk_coverage.png"); plt.close(fig)


def fig_heatmap(byv, out):
    d = byv[byv.condition == "uncertainty"]
    models = sorted(d.model.unique())
    # "missing" has no escalation-required episodes by design; omit its column
    variants = [v for v in VARIANTS if v != "missing"]
    labels = [l for v, l in zip(VARIANTS, VARIANT_LABELS) if v != "missing"]
    mat = np.full((len(models), len(variants)), np.nan)
    for i, m in enumerate(models):
        for j, v in enumerate(variants):
            row = d[(d.model == m) & (d.perturbation == v)]
            if len(row):
                mat[i, j] = row.esc_sensitivity.iloc[0]
    fig, ax = plt.subplots(figsize=(6.4, 3.2))
    im = ax.imshow(mat, cmap="Blues", vmin=0, vmax=1, aspect="auto")
    ax.set_xticks(range(len(variants)), labels)
    ax.set_yticks(range(len(models)), models)
    ax.grid(False)
    for i in range(len(models)):
        for j in range(len(variants)):
            if not np.isnan(mat[i, j]):
                ax.text(j, i, f"{mat[i, j]:.2f}", ha="center", va="center",
                        fontsize=8.5,
                        color="#ffffff" if mat[i, j] > 0.6 else "#1a1a19")
    fig.colorbar(im, ax=ax, shrink=0.85, label="Escalation sensitivity")
    ax.set_title("Escalation sensitivity by workflow perturbation "
                 "(uncertainty-prompted, test split)", fontsize=10)
    fig.tight_layout()
    fig.savefig(out / "fig2_heatmap_sensitivity.png"); plt.close(fig)


def fig_utility(sweeps, out):
    models = sorted(sweeps.keys())
    ncols = 3 if len(models) > 4 else 2
    nrows = int(np.ceil(len(models) / ncols))
    fig, axes = plt.subplots(nrows, ncols, figsize=(4 * ncols, 3.2 * nrows),
                             sharex=True, sharey=True, squeeze=False)
    for ax, model in zip(axes.flat, models):
        s = sweeps[model]
        for name, color in [("5:1", "#2a78d6"), ("10:1", "#eb6834")]:
            ax.plot(s["threshold"], s[f"utility_{name}"], color=color,
                    label=f"confidence-threshold policy, cost {name}")
            cp = s["controller_point"][name]
            ax.axhline(cp, color=color, linestyle=":", linewidth=1.4)
            ax.annotate(f"controller {cp:.2f}", xy=(0.02, cp),
                        fontsize=7.5, color=color,
                        xytext=(0.02, cp + 0.06))
        ax.set_title(model, fontsize=9.5)
    for ax in axes.flat[len(models):]:
        ax.set_visible(False)
    for ax in axes[-1]:
        ax.set_xlabel("Confidence threshold t (below t: escalate)")
    for ax in axes[:, 0]:
        ax.set_ylabel("Cost-sensitive utility")
    axes.flat[0].legend(frameon=False, fontsize=7.5, loc="lower left")
    fig.suptitle("Utility vs. escalation threshold; dotted = workflow-aware "
                 "controller (test split)", fontsize=11)
    fig.tight_layout(rect=[0, 0, 1, 0.97])
    fig.savefig(out / "fig3_utility_threshold.png"); plt.close(fig)


def fig_paired_deltas(byv, out):
    d = byv[byv.condition == "uncertainty"]
    models = sorted(d.model.unique())
    perts = VARIANTS[1:]
    x = np.arange(len(perts))
    width = 0.8 / len(models)
    fig, axes = plt.subplots(1, 2, figsize=(9, 3.6))
    for ax, metric, title in [
            (axes[0], "decision_accuracy", "Decision accuracy: variant - clean"),
            (axes[1], "esc_sensitivity", "Escalation sensitivity: variant - clean")]:
        for k, m in enumerate(models):
            dm = d[d.model == m].set_index("perturbation")
            clean = dm.loc["clean", metric]
            deltas = [dm.loc[p, metric] - clean if p in dm.index else np.nan
                      for p in perts]
            ax.bar(x + k * width - 0.4 + width / 2, deltas, width * 0.92,
                   color=MODEL_COLORS[k], label=m)
        ax.axhline(0, color="#6b6a63", linewidth=0.8)
        ax.set_xticks(x, [v.replace("_", "-") for v in perts])
        ax.set_title(title, fontsize=9.5)
        ax.set_ylabel("Delta vs. clean")
    axes[1].legend(frameon=False, fontsize=7.5, loc="upper left")
    fig.suptitle("Paired effect of workflow perturbations "
                 "(uncertainty-prompted, test split)", fontsize=11)
    fig.tight_layout(rect=[0, 0, 1, 0.94])
    fig.savefig(out / "fig4_paired_deltas.png"); plt.close(fig)


def fig_reliability(pred, out):
    d = pred[(pred.condition == "uncertainty") & (pred.split == "test")].dropna(
        subset=["action", "confidence"])
    d = d.assign(correct=[a in set(eval(acc)) if isinstance(acc, str) else a in set(acc)
                          for a, acc in zip(d.action, d.acceptable)])
    models = sorted(d.model.unique())
    fig, axes = plt.subplots(1, len(models), figsize=(2.4 * len(models), 2.8),
                             sharey=True)
    bins = np.linspace(0, 1, 11)
    for ax, m in zip(np.atleast_1d(axes), models):
        g = d[d.model == m]
        centers, accs, sizes = [], [], []
        for i in range(10):
            mask = (g.confidence > bins[i]) & (g.confidence <= bins[i + 1])
            if i == 0:
                mask |= g.confidence == 0
            if mask.sum() >= 3:
                centers.append((bins[i] + bins[i + 1]) / 2)
                accs.append(g[mask].correct.mean())
                sizes.append(mask.sum())
        ax.plot([0, 1], [0, 1], color="#6b6a63", linewidth=0.9, linestyle="--")
        ax.plot(centers, accs, color="#2a78d6", marker="o", markersize=4)
        for cx, cy, s in zip(centers, accs, sizes):
            ax.annotate(str(s), (cx, cy), fontsize=6, xytext=(0, 5),
                        textcoords="offset points", ha="center", color="#6b6a63")
        ax.set_title(m, fontsize=9)
        ax.set_xlim(0, 1); ax.set_ylim(0, 1)
        ax.set_xlabel("Stated confidence")
    np.atleast_1d(axes)[0].set_ylabel("Decision accuracy")
    fig.suptitle("Reliability: stated confidence vs. decision correctness "
                 "(bin sizes annotated)", fontsize=10.5)
    fig.tight_layout(rect=[0, 0, 1, 0.93])
    fig.savefig(out / "fig5_reliability.png"); plt.close(fig)


def main():
    run_dir = Path(sys.argv[1])
    mdir = run_dir / "metrics"
    out = run_dir / "figures"
    out.mkdir(exist_ok=True)

    rc = json.load(open(mdir / "risk_coverage.json"))
    sweeps = json.load(open(mdir / "utility_sweeps.json"))
    byv = pd.read_csv(mdir / "by_variant.csv")
    pred = pd.read_csv(mdir / "predictions_long.csv")

    fig_risk_coverage(rc, out)
    fig_heatmap(byv, out)
    fig_utility(sweeps, out)
    fig_paired_deltas(byv, out)
    fig_reliability(pred, out)
    print("figures written to", out)


if __name__ == "__main__":
    main()
