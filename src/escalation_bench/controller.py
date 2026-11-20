"""Workflow-aware selective controller.

Combines model uncertainty with text-derived workflow-state indicators into a
risk score R and overrides the base model action when R crosses tuned
thresholds. Training-free: weights and thresholds are chosen by grid search
on the dev split against the cost-sensitive utility.

  R = w_u * (1 - confidence) + w_c * C + w_m * M + w_h * H

  R >= tau_high              -> ESCALATE
  tau_low <= R < tau_high    -> ANSWER becomes ASK_CLARIFICATION, else keep
  R < tau_low                -> keep the model's action
"""
import itertools

import numpy as np

WEIGHT_GRID = [0.0, 0.25, 0.5, 0.75, 1.0]
TAU_GRID = [round(0.2 + 0.15 * i, 2) for i in range(9)]  # 0.2 .. 1.4


def risk_scores(conf, C, M, H, w):
    w_u, w_c, w_m, w_h = w
    return w_u * (1.0 - conf) + w_c * C + w_m * M + w_h * H


def apply_policy(base_actions, R, tau_low, tau_high):
    out = np.array(base_actions, dtype=object).copy()
    mid = (R >= tau_low) & (R < tau_high)
    out[mid & (out == "ANSWER")] = "ASK_CLARIFICATION"
    out[R >= tau_high] = "ESCALATE"
    return out


def utility(actions, esc_required, c_fn=5.0, c_fp=1.0, u_tp=1.0, u_tn=1.0):
    esc = actions == "ESCALATE"
    req = np.asarray(esc_required, dtype=bool)
    tp = (esc & req).sum()
    tn = (~esc & ~req).sum()
    fn = (~esc & req).sum()
    fp = (esc & ~req).sum()
    return (u_tp * tp + u_tn * tn - c_fn * fn - c_fp * fp) / len(actions)


def decision_accuracy(actions, acceptable_sets):
    return np.mean([a in acc for a, acc in zip(actions, acceptable_sets)])


def tune(dev, c_fn=5.0):
    """dev: dict of numpy arrays: conf, C, M, H, base_action, esc_required,
    acceptable (list of sets). Returns best params + dev scores."""
    best = None
    conf, C, M, H = dev["conf"], dev["C"], dev["M"], dev["H"]
    base = np.array(dev["base_action"], dtype=object)
    for w in itertools.product(WEIGHT_GRID, repeat=4):
        if sum(w) == 0:
            continue
        R = risk_scores(conf, C, M, H, w)
        for tau_low, tau_high in itertools.combinations(TAU_GRID, 2):
            acts = apply_policy(base, R, tau_low, tau_high)
            u = utility(acts, dev["esc_required"], c_fn=c_fn)
            acc = decision_accuracy(acts, dev["acceptable"])
            key = (u, acc)
            if best is None or key > best["key"]:
                best = {"key": key, "w": w, "tau_low": tau_low,
                        "tau_high": tau_high, "dev_utility": float(u),
                        "dev_decision_acc": float(acc)}
    best.pop("key")
    return best
