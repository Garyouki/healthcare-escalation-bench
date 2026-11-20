"""The scorer must reproduce the paper's published main-table numbers from the
bundled raw model outputs."""
import json
from importlib import resources
from pathlib import Path

import pytest

from escalation_bench.scoring import load_predictions, score

RAW = Path(__file__).resolve().parent.parent / "results" / "run_combined_5models" / "raw"
pytestmark = pytest.mark.skipif(not RAW.is_dir(), reason="paper run outputs not present")

# Published values (paper Table: test split, 320 episodes).
PAPER = {
    ("qwen3.5:9b", "uncertainty"): (0.850, 0.68, 0.32, 0.375),
    ("qwen3.5:9b", "vanilla"): (0.809, 0.52, 0.48, 0.094),
    ("gemma3:4b", "vanilla"): (0.775, 0.64, 0.36, 0.300),
    ("qwen3:4b", "uncertainty"): (0.613, 0.54, 0.46, 0.113),
    ("llama3.2:3b", "uncertainty"): (0.469, 0.10, 0.90, -0.688),
    ("qwen3:1.7b", "vanilla"): (0.388, 0.02, 0.98, -0.838),
}


def _run(model, condition):
    path = RAW / f"{model.replace(':', '_')}_{condition}.jsonl"
    return score(load_predictions(path), "test", n_boot=0)["overall"]


@pytest.mark.parametrize("key", sorted(PAPER))
def test_published_main_table(key):
    o = _run(*key)
    acc, sens, missed, u5 = PAPER[key]
    assert o["n"] == 320
    assert round(o["decision_accuracy"], 3) == pytest.approx(acc, abs=1e-3)
    assert round(o["esc_sensitivity"], 2) == pytest.approx(sens, abs=1e-2)
    assert round(o["missed_escalation_rate"], 2) == pytest.approx(missed, abs=1e-2)
    assert round(o["utility_5:1"], 3) == pytest.approx(u5, abs=1e-3)


def test_bundled_baselines_are_current():
    path = resources.files("escalation_bench") / "data" / "paper_baselines.json"
    base = json.loads(path.read_text(encoding="utf-8"))["test"]
    names = {"Qwen3.5-9B": "qwen3.5:9b", "Gemma-3-4B": "gemma3:4b",
             "Llama-3.2-3B": "llama3.2:3b", "Qwen3-1.7B": "qwen3:1.7b", "Qwen3-4B": "qwen3:4b"}
    for name, model in names.items():
        o = _run(model, "uncertainty")
        for k, v in base[name].items():
            assert o[k] == pytest.approx(v)
