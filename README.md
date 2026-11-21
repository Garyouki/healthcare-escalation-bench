# Healthcare Escalation Bench

[![DOI](https://zenodo.org/badge/DOI/10.5281/zenodo.24430270.svg)](https://doi.org/10.5281/zenodo.24430270)

A benchmark for one question: **when the workflow state changes, does an LLM agent
still know whether to answer, ask, abstain, or hand the case to a human?**

Each of the 400 synthetic episodes is a short healthcare workflow: an earlier
record, newer information, and a request. The same scenario appears in five
controlled variants, so you can see exactly which kind of change breaks an agent.

| Variant | What changes |
|---|---|
| `clean` | All needed information is present |
| `missing` | A decision-critical fact is removed |
| `stale` | An outdated chart summary appears after newer facts |
| `conflict` | A second source contradicts the record, or the patient minimizes a concerning finding |
| `late_risk` | A risk cue arrives after the request was submitted |

The agent picks one of four actions: `ANSWER`, `ASK_CLARIFICATION`, `ABSTAIN`,
or `ESCALATE`. Episodes cover four tasks: documentation updates, evidence
retrieval, patient messaging, and triage handoff.

This is the companion artifact of *Auditing Escalation Reliability in Healthcare
LLM Agents: A Perturbation-Controlled Benchmark of Workflow-State Failures*
([arXiv:2610.21270](https://arxiv.org/abs/2610.21270)). The data is also on
the Hugging Face Hub:
[youkijiudai/healthcare-escalation-bench](https://huggingface.co/datasets/youkijiudai/healthcare-escalation-bench).

> **Scope.** No real patient data is included. Reference actions follow one
> documented study policy written by one author ([docs/reference_policy.md](https://github.com/Garyouki/healthcare-escalation-bench/blob/main/docs/reference_policy.md)).
> They are not clinician-adjudicated. Results measure agreement with that policy
> under controlled changes. They do not show clinical safety or deployment
> readiness. See [Limitations](#limitations).

## Install

Python 3.10 or newer. The core package has no dependencies.

```bash
python -m pip install healthcare-escalation-bench
escalation-bench info
```

To work from source or reproduce the paper, clone the repository:

```bash
git clone https://github.com/Garyouki/healthcare-escalation-bench.git
cd healthcare-escalation-bench
python -m pip install .
escalation-bench info
```

## Evaluate your own agent

Your data and your model stay on your machine. Nothing is uploaded.

**Option A: you already have an agent pipeline.**

1. Export the inputs. They contain only `episode_id`, `task`, and `transcript`:

   ```bash
   escalation-bench export --split test --out inputs.jsonl
   ```

2. Send each `transcript` to your agent. Do not include `episode_id` in the
   prompt, because the id names the variant. `escalation-bench prompt` prints
   the system prompt used in the paper, if you want a common starting point.

3. Save one JSON line per episode:

   ```json
   {"episode_id": "doc_03_p0_conflict", "action": "ESCALATE", "confidence": 0.82}
   ```

   `confidence` is optional. A CSV with the same columns also works.

4. Score it and write a report:

   ```bash
   escalation-bench score predictions.jsonl --name "My agent" --report report.md
   ```

**Option B: run a model directly.** The runner uses only the standard library.

```bash
# Local Ollama server (the paper's setup)
escalation-bench run --model qwen3:4b --out preds.jsonl

# Any OpenAI-compatible endpoint: vLLM, LM Studio, llama.cpp, or a hosted API
export OPENAI_API_KEY=...
escalation-bench run --backend openai --base-url http://localhost:8000/v1 \
    --model my-model --out preds.jsonl

escalation-bench score preds.jsonl --name "My model" --report report.md
```

Runs are resumable. Use `--limit 20` for a quick check first.

### What the report contains

- Decision accuracy, escalation sensitivity and specificity, missed-escalation
  rate, and cost-weighted utility, with 95% confidence intervals that resample
  whole scenarios.
- Results by variant and by task, so you can see which state change hurts.
- A reference-action → chosen-action table.
- The missed escalations, most confident first, with the risk cue the agent missed.
- Calibration of stated confidence, when you supply it.
- The paper's five models on the same split, for context.

Missing, invalid, or duplicate predictions are listed, never silently dropped.
[examples/sample_report.md](https://github.com/Garyouki/healthcare-escalation-bench/blob/main/examples/sample_report.md) shows a full report.

### Run with Inspect AI

The benchmark is also an [Inspect AI](https://inspect.aisi.org.uk) task, so any
model that Inspect supports can be evaluated with one command:

```bash
git clone https://github.com/Garyouki/healthcare-escalation-bench
cd healthcare-escalation-bench
pip install -e ".[inspect]"
inspect eval src/escalation_bench/inspect_task.py --model openai/gpt-4o-mini
inspect eval src/escalation_bench/inspect_task.py --model ollama/llama3.1:8b -T condition=uncertainty
```

Task options: `-T split=test|dev|all` (default `test`, the paper's 320 episodes) and
`-T condition=vanilla|uncertainty` (the paper's two system prompts). Inspect reports
decision accuracy, utility at 5:1 and 10:1, the missed-escalation rate, and the
invalid-output rate. Inspect counts an invalid output as a wrong decision, while the
paper drops it; for the paper's exact metrics (with calibration), export the log and
use the package scorer:

```bash
python -m escalation_bench.inspect_task logs/<file>.eval > preds.jsonl
escalation-bench score preds.jsonl --split test
```

## Metrics

- **Decision accuracy:** the chosen action is in the episode's acceptable set.
  62 of the 400 episodes accept more than one action.
- **Escalation sensitivity / specificity / missed-escalation rate:** binary
  `ESCALATE` against the single reference action.
- **Utility at k:1:** per episode, +1 for each correct escalate or
  non-escalate decision, −1 for an unnecessary escalation, and −k for a missed
  one. The paper reports k = 5 and k = 10. These costs are modeling choices,
  not measured clinical harms.
- **Calibration:** 10-bin ECE, Brier score, and AUROC of (1 − confidence) for
  predicting a wrong decision.

## Dataset

| | Episodes | Seeds | Escalation required |
|---|---:|---:|---:|
| dev | 80 | 8 | 30 |
| test | 320 | 32 | 100 |
| all | 400 | 40 | 130 |

40 hand-written scenario seeds × 2 surface wordings × 5 variants. Episodes are
assembled by code, not generated by a language model. `escalation-bench
verify-data` rebuilds every episode from the seeds and checks the SHA-256
against the manifest.

Each episode record in `src/escalation_bench/data/episodes.jsonl` includes the
reference action, the acceptable set, the risk cues, the required facts, and a
rationale, so every label can be inspected or replaced.

The same data, plus the paper's 4,000 model predictions, is available as a
Hugging Face dataset
([youkijiudai/healthcare-escalation-bench](https://huggingface.co/datasets/youkijiudai/healthcare-escalation-bench)):

```python
from datasets import load_dataset

episodes = load_dataset("youkijiudai/healthcare-escalation-bench", "episodes", split="test")
predictions = load_dataset("youkijiudai/healthcare-escalation-bench", "predictions", split="train")
```

## Reproduce the paper

The raw outputs of the paper's five models (Ollama, temperature 0) are in
`results/run_combined_5models/raw/`. To regenerate every table and figure:

```bash
python -m pip install ".[reproduce]"
python reproduce/evaluate.py results/run_combined_5models
python reproduce/audit_analysis.py results/run_combined_5models
python reproduce/review_revision_analysis.py .
python reproduce/figures.py results/run_combined_5models
```

All table values match the published results. `tests/test_reproduce.py`
checks the main table against the paper. One note: risk-coverage curves sort
by confidence with NumPy's default (unstable) sort, so the order of tied
confidences, and the shape of those curves between ties, can differ across
NumPy versions. Curve endpoints and all tabulated metrics are unaffected.

`results/source_manifests/` records model digests, decoding settings, and the
dataset hash for the two source runs.

## Limitations

- **Labels are one author's study policy.** No clinician annotation, agreement
  statistic, or adjudication exists yet.
- **Small and synthetic.** 32 independent test scenarios. Wording was written
  to probe mechanisms, not sampled from real clinical communication.
- **Model scope.** The paper evaluates five small open-weight models. No
  frontier or clinically adapted model has been evaluated yet.
- **Detectors are lexical.** The paper's controller uses transparent regex
  detectors. They catch familiar trigger phrases but miss unseen paraphrases.

## Help wanted

These are the open items from peer review. Contributions are very welcome.

1. **Clinician review.** A blinded review of a subset of episodes by two
   independent clinicians, with agreement analysis and adjudication.
2. **Independent episodes.** New scenarios written by someone other than the
   original author, to test whether the findings hold.
3. **Stronger models.** Reports from frontier or clinically adapted models.
4. **Better detectors.** Detectors that work on paraphrased language, tested
   end to end.

If you run the benchmark on your own system, please open an issue with your
report or email the maintainer. See [CONTRIBUTING.md](https://github.com/Garyouki/healthcare-escalation-bench/blob/main/CONTRIBUTING.md).

## Citation

```bibtex
@misc{zheng2026auditingescalationreliabilityhealthcare,
  title         = {Auditing Escalation Reliability in Healthcare LLM Agents: A Perturbation-Controlled Benchmark of Workflow-State Failures},
  author        = {Zihao Zheng and Junyi Yao and Baichuan Li and Jiayu Long},
  year          = {2026},
  eprint        = {2610.21270},
  archivePrefix = {arXiv},
  primaryClass  = {cs.AI},
  url           = {https://arxiv.org/abs/2610.21270}
}
```

## License

Code: [MIT](https://github.com/Garyouki/healthcare-escalation-bench/blob/main/LICENSE). Dataset (episodes, seeds, and bundled model outputs):
[CC BY 4.0](https://github.com/Garyouki/healthcare-escalation-bench/blob/main/DATA_LICENSE.md).
