#!/usr/bin/env python3
"""Post-exit collector process for a launcher-owned shared mapping."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from faultdebug.collector import main


if __name__ == "__main__":
    raise SystemExit(main())
