from __future__ import annotations

import os
import sys
from pathlib import Path

# The repository .env configures the real desktop for Firebase/Cloud Run.  API
# tests exercise the explicit local-development contract unless a test opts
# into Firebase itself, so they must not inherit private workstation auth.
os.environ["SERVO_AUTH_MODE"] = "local"
os.environ["SERVO_API_TOKEN"] = ""

REPOSITORY = Path(__file__).resolve().parents[2]
if str(REPOSITORY) not in sys.path:
    sys.path.insert(0, str(REPOSITORY))
