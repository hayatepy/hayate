"""Shared test configuration."""

import sys
from pathlib import Path

# Make examples/ importable so samples are tested exactly as shipped.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "examples"))
