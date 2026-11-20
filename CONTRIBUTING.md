# Contributing

Thank you for helping make this benchmark more trustworthy. The most useful
contributions are the ones the original study could not do alone.

## Share an evaluation report

Ran the benchmark on your agent or model? Open an issue titled
`Report: <system name>` and attach the Markdown report from
`escalation-bench score ... --report report.md`. Please include:

- the model or agent, its version, and how it was served;
- the system prompt (or say that you used `escalation-bench prompt`);
- decoding settings such as temperature;
- anything you changed in the inputs.

You do not need to share your predictions file, but it helps others reproduce
your numbers.

## Clinician review

The reference actions were written by one author and have not been reviewed by
clinicians. If you are a clinician or clinical informaticist and can review a
subset of episodes blind to the reference labels, please open an issue or email
the maintainer. A review protocol, a labeling sheet, and an agreement analysis
are ready to be set up together. Reviewers will be credited.

## New episodes

Independently written scenarios are the best test of whether the findings
generalize. A new seed follows the schema in
`src/escalation_bench/seeds/common.py`. It needs a setting, a baseline record,
the content for each of the five variants, a reference action per variant, the
risk cues, and a short rationale. Please open an issue first so we can agree on
the label policy before you write many seeds.

## Code changes

1. Create a virtual environment and run `python -m pip install -e ".[dev]"`.
2. Run `python -m pytest`. All tests must pass.
3. Do not change `episodes.jsonl` by hand. Change the seeds and confirm the
   result with `escalation-bench verify-data`. A dataset change needs a new
   version number and a note in `CHANGELOG.md`, because reported results depend
   on the exact dataset.
4. Keep the core package free of third-party dependencies.

## Scope

Please do not submit real patient data, including de-identified records. This
repository only holds synthetic material.
