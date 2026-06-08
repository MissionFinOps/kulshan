# Contributing

## Project Structure

```
mission-finops/
├── Kulshan/                # The Python package (one wheel: kulshan)
│   ├── pyproject.toml
│   ├── iam/
│   │   ├── Kulshan-readonly.json     # composed IAM policy (union)
│   │   └── per-check/<key>.json       # 10 per-pack policies
│   ├── src/kulshan/
│   │   ├── cli.py / orchestrator.py / session.py
│   │   ├── report/                    # HTML / JSON / terminal renderers
│   │   └── checks/<key>/              # 10 internal audit packs
│   └── tests/
│       ├── unit/ integration/ property/ e2e/
│       └── fixtures/
├── docs/                    # Documentation (you are here)
├── tools/                   # Archived standalone CLIs (historical only)
└── index.html               # Website landing page
```

The ten check packs live at `Kulshan.checks.<key>` (cost, security, sweep, dr, age, drift, tag, pulse, limit, topo). They are not separately installable.

---

## Development Setup

```bash
git clone <this-repo>
cd mission-finops
pip install -e "Kulshan[dev]"    # installs with pytest, ruff, mypy, moto, hypothesis
```

## Code Style

- Python 3.9+
- Type hints on all public functions
- Docstrings on all modules and public functions
- `from __future__ import annotations` in every file
- Ruff formatting (line length 100)
- No star imports

---

## Authoring Check Packs

### Pack structure

```
kulshan/src/kulshan/checks/<key>/
├── __init__.py            # exposes run_scan()
├── scanner/
│   └── module.py          # AWS API calls + data collection
├── scoring/
│   └── engine.py          # 0-100 score calculation
└── utils/
    └── aws.py             # boto3 helpers
```

### The contract

Every pack's `__init__.py` must expose:

```python
def run_scan(session, regions, *, quick=False, profile=None, **kwargs) -> dict:
```

Return shape:

```python
{
    "tool": str,                    # pack key (e.g. "cost")
    "scores": {
        "overall_score": int,       # 0-100
        "grade": str,               # A+ through F
        "total_findings": int,
        "severity_counts": {"critical": 0, "high": 0, "medium": 0, "low": 0, "info": 0},
    },
    "findings": [...],              # canonical Finding dicts (see finding-schema.md)
    "errors": [],                   # error strings (empty if clean)
}
```

### Scanner rules

1. Accept `session` (boto3) and `regions` (list of strings)
2. Use pagination for all List/Describe calls
3. Handle `AccessDenied` gracefully — log, skip, don't crash
4. **Never write to AWS** — read-only only

Example:

```python
def scan(session, regions):
    findings = []
    for region in regions:
        client = session.client("ec2", region_name=region)
        try:
            paginator = client.get_paginator("describe_instances")
            for page in paginator.paginate():
                # inspect resources, emit findings
                pass
        except client.exceptions.ClientError as e:
            if e.response["Error"]["Code"] == "AccessDenied":
                logging.warning(f"AccessDenied in {region}, skipping")
                continue
            raise
    return findings
```

### Scoring

Return a 0-100 integer. Grade mapping (A+ through F) is handled by the orchestrator.

### Emitting findings

Use the canonical shape from [finding-schema.md](finding-schema.md). Required fields: `id`, `pack`, `kind`, `title`, `severity`, `confidence`, `effort`, `risk`.

---

## Adding a New Pack

1. Create `kulshan/src/kulshan/checks/<key>/` with the structure above
2. Add to `TOOL_ORDER`, `TOOL_LABELS`, `TOOL_WEIGHTS` in `orchestrator.py`
3. Author `kulshan/iam/per-check/<key>.json` and update `Kulshan-readonly.json`
4. Add fixture at `tests/fixtures/checks/<key>.json`
5. Add doc at `docs/checks/<key>.md`
6. Run `pytest tests/unit/test_check_pack_contract.py`

## Adding a Check to an Existing Pack

1. Add scanner logic in `checks/<key>/scanner/`
2. Update the scoring engine
3. Add unit tests
4. Update `docs/checks/<key>.md`

---

## Testing

```bash
pytest                                    # full suite
pytest tests/unit/ -v                     # unit only
pytest tests/property/ -v                 # property-based (Hypothesis)
pytest --cov=kulshan --cov-report=term   # with coverage
```

### Mocking AWS

Tests never call real AWS. They use:
- `botocore.stub.Stubber` for unit tests
- Fixture files in `tests/fixtures/aws_responses/`
- `moto` for complex scenarios

### Test Fixtures

All fixtures live at `Kulshan/tests/fixtures/`:

| Directory | Purpose |
|-----------|---------|
| `aws_responses/` | Mocked boto3 responses |
| `checks/` | Expected `run_scan()` output (snapshot tests) |
| `cost/` | Cost Explorer response fixtures |
| `scan_results/` | Full scan results for e2e tests |

To add a fixture: capture a real (sanitized) response or build it manually. Name it `<service>_<operation>_<scenario>.json`.

### Sample report

```bash
python Kulshan/scripts/generate_sample_report.py
```

Generates the synthetic sample at `sample/index.html` using fixture data through the real renderer.

---

## Git Workflow

```bash
git checkout -b feature/my-change
# make changes
git add -A
git commit -m "Add thing"
git checkout master
git merge feature/my-change
```
