"""Shared, local evaluation tools for Assermetry.

Run with PYTHONPATH=tests python -m evaluation.pipeline (or llm_benchmark).
"""

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT / "api") not in sys.path:
    sys.path.insert(0, str(ROOT / "api"))
