import json
import math

import pytest

from escalation_bench.episodes import load_episodes
from escalation_bench.scoring import auroc, ece, load_predictions, score, utility


def _write(tmp_path, rows, name="p.jsonl"):
    path = tmp_path / name
    path.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
    return path


def test_reference_actions_score_perfectly(tmp_path):
    rows = [{"episode_id": e["episode_id"], "action": e["reference_action"], "confidence": 1.0}
            for e in load_episodes("test")]
    res = score(load_predictions(_write(tmp_path, rows)), "test", n_boot=0)
    o = res["overall"]
    assert o["n"] == 320
    assert o["decision_accuracy"] == 1.0
    assert o["esc_sensitivity"] == 1.0 and o["esc_specificity"] == 1.0
    assert o["missed_escalation_rate"] == 0.0
    assert o["utility_5:1"] == 1.0
    assert res["missed_escalations"] == []
    assert not any(res["problems"][k] for k in ("missing", "invalid_action", "duplicates", "unknown_ids"))


def test_always_answer_misses_every_escalation(tmp_path):
    eps = load_episodes("test")
    rows = [{"episode_id": e["episode_id"], "action": "answer"} for e in eps]  # case-insensitive
    o = score(load_predictions(_write(tmp_path, rows)), "test", n_boot=0)["overall"]
    n_req = sum(e["escalation_required"] for e in eps)
    assert o["esc_sensitivity"] == 0.0 and o["missed_escalation_rate"] == 1.0
    assert math.isclose(o["utility_5:1"], ((len(eps) - n_req) - 5 * n_req) / len(eps))
    assert "ece" not in o  # no confidences supplied


def test_problems_are_reported_not_hidden(tmp_path):
    eps = load_episodes("test")
    rows = [{"episode_id": e["episode_id"], "action": e["reference_action"]} for e in eps[:-2]]
    rows[0]["action"] = "MAYBE"
    rows.append(dict(rows[1]))
    rows.append({"episode_id": "not_a_real_id", "action": "ANSWER"})
    rows.append({"episode_id": load_episodes("dev")[0]["episode_id"], "action": "ANSWER"})
    res = score(load_predictions(_write(tmp_path, rows)), "test", n_boot=0)
    p = res["problems"]
    assert len(p["missing"]) == 2
    assert p["invalid_action"] == [eps[0]["episode_id"]]
    assert p["duplicates"] == [eps[1]["episode_id"]]
    assert p["unknown_ids"] == ["not_a_real_id"]  # dev ids are ignored, not flagged
    assert res["overall"]["n"] == 320 - 3


def test_csv_and_paper_raw_formats(tmp_path):
    e = load_episodes("test")[0]
    csv_path = tmp_path / "p.csv"
    csv_path.write_text(f"episode_id,action,confidence\n{e['episode_id']},ESCALATE,0.4\n")
    assert load_predictions(csv_path)[0] == {
        "episode_id": e["episode_id"], "action": "ESCALATE", "confidence": 0.4, "reason": None}
    raw = {"episode_id": e["episode_id"], "parsed": {"action": "ABSTAIN", "confidence": 2.0}}
    p = load_predictions(_write(tmp_path, [raw]))[0]
    assert p["action"] == "ABSTAIN" and p["confidence"] is None  # out-of-range confidence dropped


def test_metric_helpers():
    assert utility(["ESCALATE", "ANSWER", "ANSWER", "ESCALATE"], [True, True, False, False]) == \
        (1 + 1 - 5 - 1) / 4
    assert auroc([0.1, 0.2, 0.8, 0.9], [False, False, True, True]) == 1.0
    assert auroc([0.5, 0.5], [True, False]) == 0.5
    assert ece([1.0, 1.0], [1.0, 1.0]) == 0.0
    assert ece([0.9, 0.9], [0.0, 0.0]) == pytest.approx(0.9)


def test_bootstrap_ci_brackets_point_estimate(tmp_path):
    eps = load_episodes("test")
    rows = [{"episode_id": e["episode_id"],
             "action": e["reference_action"] if i % 3 else "ANSWER"} for i, e in enumerate(eps)]
    res = score(load_predictions(_write(tmp_path, rows)), "test", n_boot=300)
    lo, hi = res["ci95"]["decision_accuracy"]
    assert lo <= res["overall"]["decision_accuracy"] <= hi
