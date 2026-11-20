# Dataset license

The benchmark data in this repository is licensed under the
[Creative Commons Attribution 4.0 International License (CC BY 4.0)](https://creativecommons.org/licenses/by/4.0/).

This covers:

- `src/escalation_bench/data/` (seeds, episodes, manifest, detector stress items,
  and precomputed baseline metrics);
- `results/` (raw model outputs and run manifests from the paper).

Please cite the paper when you use the data (see `CITATION.cff`).

The episodes are fully synthetic. They contain no real patient data and are not
clinical guidance. Do not use them to make decisions about real patients.
Bundled model outputs were produced by third-party open-weight models and may
also be subject to those models' own license terms.

The code is licensed separately under the MIT License (see `LICENSE`).
