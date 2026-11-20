import json

from escalation_bench.episodes import (ACTIONS, INPUT_FIELDS, dataset_sha256,
                                       load_episodes, load_manifest, model_inputs)
from escalation_bench.generate import build_episodes, episodes_bytes


def test_counts_match_manifest():
    m = load_manifest()
    eps = load_episodes("all")
    assert len(eps) == m["n_episodes"] == 400
    assert len(load_episodes("dev")) == m["n_dev"] == 80
    assert len(load_episodes("test")) == m["n_test"] == 320
    assert sum(e["escalation_required"] for e in eps) == m["n_escalation_required"] == 130


def test_dataset_rebuilds_byte_for_byte_from_seeds():
    import hashlib
    rebuilt = hashlib.sha256(episodes_bytes(build_episodes())).hexdigest()
    assert rebuilt == dataset_sha256() == load_manifest()["dataset_sha256"]


def test_labels_are_consistent():
    for e in load_episodes("all"):
        assert e["reference_action"] in ACTIONS
        assert e["reference_action"] in e["acceptable_actions"]
        assert set(e["acceptable_actions"]) <= set(ACTIONS)
        assert e["escalation_required"] == (e["reference_action"] == "ESCALATE")


def test_model_inputs_carry_no_labels():
    rows = model_inputs("all")
    assert all(tuple(r) == INPUT_FIELDS for r in rows)
    text = json.dumps([r["transcript"] for r in rows])
    for leak in ("reference_action", "acceptable_actions", "escalation_required", "rationale"):
        assert leak not in text


def test_splits_do_not_share_seeds():
    dev = {e["seed_id"] for e in load_episodes("dev")}
    test = {e["seed_id"] for e in load_episodes("test")}
    assert dev and test and not dev & test
