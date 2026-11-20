"""Locate the bundled data and flat-importable modules for the paper scripts.

The original analysis scripts import ``detectors`` and ``controller`` as
top-level modules and read ``data/*.jsonl``. In this repository those files
live inside the ``escalation_bench`` package, so the scripts use these paths.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PKG_DIR = ROOT / "src" / "escalation_bench"
if not PKG_DIR.is_dir():  # running against an installed package
    import escalation_bench
    PKG_DIR = Path(escalation_bench.__file__).resolve().parent
DATA_DIR = PKG_DIR / "data"

if str(PKG_DIR) not in sys.path:
    sys.path.insert(0, str(PKG_DIR))


def resolve(root, rel):
    """Map a paper-repository relative path to its location here."""
    rel = str(rel)
    if rel.startswith("data/"):
        return DATA_DIR / rel[len("data/"):]
    return Path(root) / rel
