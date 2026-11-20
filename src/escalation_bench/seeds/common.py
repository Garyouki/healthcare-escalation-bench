"""Seed schema and helpers for the escalation benchmark.

A seed defines one base clinical scenario plus the content hooks needed to
assemble all five controlled variants (clean / missing / stale / conflict /
late_risk). Reference actions are defined PER VARIANT because the correct
decision changes with the perturbation.

Action semantics (fixed decision space):
  ANSWER            - complete the requested task directly (reply / note / answer)
  ASK_CLARIFICATION - request a specific missing piece of information first
  ABSTAIN           - decline: the task cannot be safely completed as posed
  ESCALATE          - route immediately to a human clinician / urgent pathway

Variant assembly conventions (see generate_episodes.py):
  clean     : baseline + update_full + request
  missing   : baseline + update_no_critical + request
  stale     : baseline + update_full + salient outdated auto-summary + request
  conflict  : baseline + update_full + conflict_addon + request
  late_risk : baseline + update_no_critical + distractor + request,
              then late_risk_cue arrives AFTER the request
"""

ACTIONS = ["ANSWER", "ASK_CLARIFICATION", "ABSTAIN", "ESCALATE"]
VARIANTS = ["clean", "missing", "stale", "conflict", "late_risk"]


def seed(seed_id, task, scenario, severity, setting, baseline, stale_fact,
         update_full, update_no_critical, critical_fact, conflict_addon,
         late_risk_cue, distractor, request, required_facts, risk_cues,
         rationale, refs, params):
    s = dict(
        seed_id=seed_id, task=task, scenario=scenario, severity=severity,
        setting=setting, baseline=baseline, stale_fact=stale_fact,
        update_full=update_full, update_no_critical=update_no_critical,
        critical_fact=critical_fact, conflict_addon=conflict_addon,
        late_risk_cue=late_risk_cue, distractor=distractor, request=request,
        required_facts=required_facts, risk_cues=risk_cues,
        rationale=rationale, refs=refs, params=params,
    )
    validate(s)
    return s


def validate(s):
    assert set(s["refs"].keys()) == set(VARIANTS), s["seed_id"]
    for v, (ref, acc) in s["refs"].items():
        assert ref in ACTIONS, (s["seed_id"], v, ref)
        assert ref in acc and all(a in ACTIONS for a in acc), (s["seed_id"], v)
    assert len(s["params"]) == 2, s["seed_id"]
    assert s["severity"] in ("low", "moderate", "high"), s["seed_id"]
