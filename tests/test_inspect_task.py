"""Smoke tests for the Inspect AI task. Skipped when inspect_ai is not installed."""
import json

import pytest

pytest.importorskip("inspect_ai")

from inspect_ai import eval as inspect_eval  # noqa: E402
from inspect_ai.model import ModelOutput, get_model  # noqa: E402

from escalation_bench.episodes import load_episodes  # noqa: E402
from escalation_bench.inspect_task import (  # noqa: E402
    healthcare_escalation,
    predictions_from_log,
)


def _reply(action, conf=0.9):
    return json.dumps({"action": action, "confidence": conf, "reason": "test"})


def _run(outputs, limit, **task_args):
    model = get_model(
        "mockllm/model",
        custom_outputs=[ModelOutput.from_content(model="mockllm/model", content=c)
                        for c in outputs],
    )
    [log] = inspect_eval(healthcare_escalation(**task_args), model=model,
                         limit=limit, max_samples=1, max_connections=1, display="none", log_dir="/tmp/heb-inspect-logs")
    assert log.status == "success", log.error
    return log


def _metrics(log):
    return {name: m.value for name, m in log.results.scores[0].metrics.items()}


def test_dataset_sizes():
    assert len(healthcare_escalation().dataset) == 320
    assert len(healthcare_escalation(split="dev").dataset) == 80
    assert len(healthcare_escalation(split="all").dataset) == 400


def test_model_never_sees_labels():
    for sample in healthcare_escalation(split="all").dataset:
        text = sample.input if isinstance(sample.input, str) else str(sample.input)
        assert "acceptable_actions" not in text
        assert "reference_action" not in text


def test_reference_actions_score_perfectly():
    eps = load_episodes("test")[:12]
    log = _run([_reply(e["reference_action"]) for e in eps], limit=12)
    m = _metrics(log)
    assert m["accuracy"] == pytest.approx(1.0)
    assert m["missed_escalation_rate"] == 0.0
    assert m["invalid_rate"] == 0.0
    assert m["utility_5to1"] == pytest.approx(1.0)


def test_invalid_output_counts_as_wrong():
    log = _run(["not json"] * 3, limit=3, condition="uncertainty")
    m = _metrics(log)
    assert m["accuracy"] == 0.0
    assert m["invalid_rate"] == 1.0


def test_log_export_matches_package_scorer_format():
    eps = load_episodes("test")[:4]
    log = _run([_reply("ESCALATE", 0.7)] * 4, limit=4)
    rows = predictions_from_log(log.location)
    assert sorted(r["episode_id"] for r in rows) == sorted(e["episode_id"] for e in eps)
    assert all(r["action"] == "ESCALATE" and r["confidence"] == 0.7 for r in rows)
