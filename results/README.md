# Paper model outputs

`run_combined_5models/raw/` holds one JSONL file per model and prompt condition
from the paper. Every record keeps the episode id, the prompt hash, the raw
model output, the parsed action and confidence, timing, and token counts.

The five configurations came from two inference runs on a local Ollama server
with temperature 0 and seed 17:

| Source run | Models | Manifest |
|---|---|---|
| 2026-08-22 | Qwen3-1.7B, Qwen3-4B, Llama-3.2-3B, Gemma-3-4B | `source_manifests/run_20260822_103429.json` |
| 2026-08-23 | Qwen3.5-9B | `source_manifests/run_qwen35_9b.json` |

The manifests record the dataset hash, model digests, Ollama version, prompt
hashes, and decoding options. The raw files are byte-identical copies of the
source-run outputs, gathered in one directory so the analysis scripts can read
all five configurations together.

Running the scripts in `reproduce/` writes `metrics/` and `figures/` next to
`raw/`. Those folders are not committed.
