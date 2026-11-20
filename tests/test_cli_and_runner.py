import json

from escalation_bench import runner
from escalation_bench.cli import main
from escalation_bench.episodes import load_episodes


def test_parse_output_variants():
    ok, err = runner.parse_output('{"action": "escalate", "confidence": 1.4, "reason": "x"}')
    assert err is None and ok == {"action": "ESCALATE", "confidence": 1.0, "reason": "x"}
    ok, _ = runner.parse_output('```json\n{"action":"ANSWER","confidence":0.7,"reason":""}\n```')
    assert ok["action"] == "ANSWER"
    assert runner.parse_output('{"action": "DEFER", "confidence": 0.5}') == (None, "invalid_action")
    assert runner.parse_output("not json")[0] is None


def test_run_is_resumable_and_sends_only_transcripts(tmp_path, monkeypatch):
    seen = []

    def fake(model, system, user, base_url=None):
        seen.append(user)
        return '{"action": "ESCALATE", "confidence": 0.9, "reason": "test"}'

    monkeypatch.setattr(runner, "call_ollama", fake)
    out = tmp_path / "preds.jsonl"
    runner.run("fake-model", out, limit=5, workers=2, log=lambda s: None)
    runner.run("fake-model", out, limit=5, workers=2, log=lambda s: None)
    recs = [json.loads(l) for l in out.read_text().splitlines()]
    assert len(recs) == 10 and len({r["episode_id"] for r in recs}) == 10
    assert all("reference_action" not in u and "_clean" not in u for u in seen)


def test_score_command_writes_report_and_json(tmp_path, capsys):
    preds = tmp_path / "p.jsonl"
    preds.write_text("".join(
        json.dumps({"episode_id": e["episode_id"], "action": "ASK_CLARIFICATION",
                    "confidence": 0.6}) + "\n" for e in load_episodes("test")))
    report, js = tmp_path / "report.md", tmp_path / "result.json"
    main(["score", str(preds), "--report", str(report), "--json", str(js),
          "--name", "Example agent", "--bootstrap", "50"])
    text = report.read_text()
    for heading in ("# Escalation reliability audit: Example agent", "## By workflow-state variant",
                    "## Missed escalations", "## Reference points from the paper"):
        assert heading in text
    assert json.loads(js.read_text())["overall"]["n"] == 320
    assert "scored 320 of 320 test episodes" in capsys.readouterr().out


def test_export_command(tmp_path):
    out = tmp_path / "inputs.jsonl"
    main(["export", "--split", "dev", "--out", str(out)])
    rows = [json.loads(l) for l in out.read_text().splitlines()]
    assert len(rows) == 80 and set(rows[0]) == {"episode_id", "task", "transcript"}
