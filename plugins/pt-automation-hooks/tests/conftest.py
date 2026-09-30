"""Puts the plugin's scripts/ on sys.path, so the Bar check imports by name.

pt_transition.py is not put here: every hook reads it from the
peech-ci-workflows clone itself (PPA-1662).

The suite runs from the plugin directory: ``python3 -m pytest tests/``.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
