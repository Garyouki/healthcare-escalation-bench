"""Command-line interface: ``escalation-bench <command>``."""
from __future__ import annotations

import argparse
import json
import sys
from importlib import resources
from pathlib import Path

from . import __version__
from .episodes import (SPLITS, dataset_sha256, episodes_path, load_episodes,
                       load_manifest, model_inputs)
from .prompts import CONDITIONS


def _baselines(split):
    path = resources.files("escalation_bench") / "data" / "paper_baselines.json"
    return json.loads(path.read_text(encoding="utf-8")).get(split)


def cmd_info(args):
    m = load_manifest()
    print(f"healthcare-escalation-bench {__version__}")
    print(f"episodes: {m['n_episodes']} from {m['n_seeds']} seeds "
          f"(dev {m['n_dev']}, test {m['n_test']})")
    print(f"escalation-required episodes: {m['n_escalation_required']}")
    print(f"tasks: {', '.join(m['episodes_per_task'])}")
    sha = dataset_sha256()
    print(f"dataset sha256: {sha}")
    print("matches manifest" if sha == m["dataset_sha256"] else "WARNING: hash mismatch")


def cmd_export(args):
    rows = model_inputs(args.split) if not args.with_labels else load_episodes(args.split)
    out = open(args.out, "w", encoding="utf-8") if args.out else sys.stdout
    for r in rows:
        out.write(json.dumps(r) + "\n")
    if args.out:
        out.close()
        kind = "episodes with labels" if args.with_labels else "model inputs (no labels)"
        print(f"wrote {len(rows)} {kind} to {args.out}", file=sys.stderr)


def cmd_prompt(args):
    print(CONDITIONS[args.condition])


def cmd_run(args):
    from .runner import run
    run(args.model, args.out, backend=args.backend, condition=args.condition,
        split=args.split, base_url=args.base_url, api_key_env=args.api_key_env,
        workers=args.workers, limit=args.limit,
        log=lambda s: print(s, file=sys.stderr))
    print(f"predictions written to {args.out}", file=sys.stderr)


def cmd_score(args):
    from .report import render
    from .scoring import load_predictions, score
    result = score(load_predictions(args.predictions), args.split, n_boot=args.bootstrap)
    if args.json:
        Path(args.json).write_text(json.dumps(result, indent=2), encoding="utf-8")
    if args.report:
        text = render(result, args.name or Path(args.predictions).stem,
                      baselines=None if args.no_baselines else _baselines(args.split))
        Path(args.report).write_text(text, encoding="utf-8")
    o, p = result["overall"], result["problems"]
    print(f"scored {o['n']} of {p['expected']} {args.split} episodes")
    for k in ("missing", "invalid_action", "duplicates", "unknown_ids"):
        if p[k]:
            print(f"  {k.replace('_', ' ')}: {len(p[k])}")
    for k in ("decision_accuracy", "esc_sensitivity", "esc_specificity",
              "missed_escalation_rate", "utility_5:1", "utility_10:1"):
        ci = result["ci95"].get(k)
        extra = f"  [95% CI {ci[0]:.3f}–{ci[1]:.3f}]" if ci else ""
        print(f"  {k:24s} {o[k]:.3f}{extra}")
    if args.report:
        print(f"report written to {args.report}")


def cmd_verify(args):
    from .generate import build_episodes, episodes_bytes
    import hashlib
    rebuilt = hashlib.sha256(episodes_bytes(build_episodes())).hexdigest()
    bundled, manifest = dataset_sha256(), load_manifest()["dataset_sha256"]
    print(f"rebuilt from seeds: {rebuilt}")
    print(f"bundled file:       {bundled}")
    print(f"manifest:           {manifest}")
    ok = rebuilt == bundled == manifest
    print("OK: dataset is reproducible from the seeds" if ok else "MISMATCH")
    sys.exit(0 if ok else 1)


def main(argv=None):
    ap = argparse.ArgumentParser(
        prog="escalation-bench",
        description="Audit whether an LLM agent escalates, asks, abstains, or answers "
                    "correctly when healthcare workflow state changes.")
    ap.add_argument("--version", action="version", version=__version__)
    sub = ap.add_subparsers(dest="command", required=True)

    s = sub.add_parser("info", help="show dataset summary and hash check")
    s.set_defaults(func=cmd_info)

    s = sub.add_parser("export", help="write model inputs (no labels) as JSONL")
    s.add_argument("--split", choices=SPLITS, default="test")
    s.add_argument("--out", help="output file (default: stdout)")
    s.add_argument("--with-labels", action="store_true",
                   help="include reference labels; never send this file to a model")
    s.set_defaults(func=cmd_export)

    s = sub.add_parser("prompt", help="print a system prompt used in the paper")
    s.add_argument("--condition", choices=sorted(CONDITIONS), default="uncertainty")
    s.set_defaults(func=cmd_prompt)

    s = sub.add_parser("run", help="run a model through Ollama or an OpenAI-compatible API")
    s.add_argument("--model", required=True)
    s.add_argument("--out", required=True, help="predictions JSONL (appended, resumable)")
    s.add_argument("--backend", choices=["ollama", "openai"], default="ollama")
    s.add_argument("--base-url", help="server URL (default depends on backend)")
    s.add_argument("--api-key-env", default="OPENAI_API_KEY",
                   help="environment variable holding the API key (openai backend)")
    s.add_argument("--condition", choices=sorted(CONDITIONS), default="uncertainty")
    s.add_argument("--split", choices=SPLITS, default="test")
    s.add_argument("--workers", type=int, default=4)
    s.add_argument("--limit", type=int, default=0, help="run only the first N episodes")
    s.set_defaults(func=cmd_run)

    s = sub.add_parser("score", help="score predictions and optionally write a report")
    s.add_argument("predictions", help="JSONL or CSV with episode_id, action[, confidence]")
    s.add_argument("--split", choices=SPLITS, default="test")
    s.add_argument("--report", help="write a Markdown audit report here")
    s.add_argument("--json", help="write full results as JSON here")
    s.add_argument("--name", help="system name shown in the report")
    s.add_argument("--bootstrap", type=int, default=2000,
                   help="seed-bootstrap draws for 95%% CIs (0 to skip)")
    s.add_argument("--no-baselines", action="store_true",
                   help="omit the paper's reference models from the report")
    s.set_defaults(func=cmd_score)

    s = sub.add_parser("verify-data", help="rebuild episodes from seeds and check hashes")
    s.set_defaults(func=cmd_verify)

    args = ap.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
