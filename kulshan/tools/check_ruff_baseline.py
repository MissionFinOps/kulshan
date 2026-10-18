"""Reject new configured Ruff debt by file/rule; never hide the full lint result."""
from __future__ import annotations

import collections
import json
import subprocess
import sys
from pathlib import Path

root = Path(__file__).resolve().parents[1]
baseline = json.loads((root / "tools/ruff-baseline.json").read_text(encoding="utf-8"))
result = subprocess.run(
    [sys.executable, "-m", "ruff", "check", "src", "tests", "--output-format", "json"],
    cwd=root, capture_output=True, text=True, check=False,
)
if result.returncode not in (0, 1):
    sys.exit(result.stderr or "Ruff invocation failed")
items = json.loads(result.stdout)
counts = collections.Counter(
    f"{Path(item['filename']).relative_to(root).as_posix()}|{item['code']}" for item in items
)
regressions = {key: count - baseline.get(key, 0) for key, count in counts.items()
               if count > baseline.get(key, 0)}
print(f"Configured Ruff: {len(items)} residual violations; baseline {sum(baseline.values())}.")
for key, increase in sorted(regressions.items()):
    print(f"  {key}: +{increase}")
sys.exit(bool(regressions))
