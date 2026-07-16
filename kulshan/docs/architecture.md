# Architecture & Internals

This document describes Kulshan's internal architecture for contributors, auditors, and anyone wanting to understand how the tool works.

---

## Module Layout

```
src/kulshan/
├── __init__.py
├── __version__.py          # Single source of truth for version
├── cli.py                  # Click-based CLI entry point
├── orchestrator.py         # Pack execution, scoring, validation
├── constants.py            # Exit codes, placeholder endpoints
├── models.py              # Canonical data models (Finding, ScanResult, etc.)
├── session.py             # AWS session creation, region discovery
├── parallel.py            # Parallel execution utilities
├── adapter.py             # Legacy-to-canonical finding adapter
├── aws_runtime.py         # API profiling, call tracking
├── preflight.py           # Pre-scan health checks
├── consolidated.py        # Multi-connection consolidated reports
├── scoring_utils.py       # Score computation, grading
├── findings.py            # Fingerprinting, deduplication
├── findings_processor.py  # Finding ranking, top-actions extraction
├── findings_ranker.py     # Priority scoring for remediation
├── redact.py              # PII/account ID redaction
├── remediation.py         # Remediation action generation
├── repl.py                # Interactive shell (prompt_toolkit)
├── completion.py          # Shell tab completion
├── help_formatter.py      # Rich-formatted help output
├── question_mark.py       # Inline ? help system
├── setup.py               # CLI setup orchestrator
├── theme.py               # Color theme engine
├── theme_constants.py     # Per-pack color definitions
├── diagnostics.py         # Debug/diagnostic output
├── errors.py              # Custom exception hierarchy
│
├── checks/                # Audit packs (one directory per pack)
│   ├── cost/
│   ├── security/
│   ├── sweep/
│   ├── dr/
│   ├── age/
│   ├── drift/
│   ├── tag/
│   ├── pulse/
│   ├── limit/
│   └── topo/
│
├── report/                # Output renderers
│   ├── terminal.py        # Rich terminal output
│   ├── html.py            # Jinja2 HTML report
│   ├── sarif.py           # SARIF 2.1.0 generation
│   └── csv_export.py      # CSV export
│
├── workspace/             # Multi-environment isolation
│   ├── cli.py             # Workspace subcommands
│   ├── config.py          # Config data models, TOML I/O
│   ├── context.py         # WorkspaceContext resolution
│   ├── execution.py       # AWS execution context
│   ├── onboarding.py      # Auto-onboarding flow
│   ├── payer_binding.py   # CUR-based payer binding
│   ├── reconcile.py       # Payer reconciliation
│   ├── registry.py        # Identity → workspace mapping
│   ├── resolution.py      # Workspace resolution logic
│   ├── sts.py             # STS identity verification
│   ├── federated_history.py  # Cross-workspace history
│   ├── migration.py       # Schema migration
│   ├── paths.py           # Data directory paths
│   ├── validation.py      # Input validation
│   ├── wordlist.py        # Display name generation
│   └── errors.py          # Workspace-specific errors
│
├── history/               # Scan history persistence
├── config/                # Configuration loading
├── cur/                   # CUR/Data Export handling
├── investigate/           # Cost investigation commands
├── mcp_server/            # MCP protocol server
│   ├── server.py          # MCP server implementation
│   └── tools.py           # Tool definitions
├── slm/                   # Local SLM integration
├── trust/                 # Trust/verification utilities
├── license/               # License management
├── telemetry/             # Telemetry (placeholder, inactive)
├── plugins/               # Plugin system
├── ci/                    # CI/CD utilities
├── adapters/              # AWS service adapters
└── utils/                 # Shared utilities
```

---

## Data Flow

### Report execution

```
CLI (cli.py)
  │
  ├─ Credential resolution (workspace/resolution.py, workspace/sts.py)
  │   └─ Auto-onboarding if new identity (workspace/onboarding.py)
  │
  ├─ Pre-flight checks (preflight.py)
  │   └─ CUR discovery, permission validation
  │
  ├─ Pack selection & region resolution
  │
  ├─ Orchestrator (orchestrator.py)
  │   ├─ Parallel pack execution
  │   │   └─ Each pack: checks/<pack>/ → list of findings
  │   ├─ Finding validation (canonical schema)
  │   ├─ Score computation (scoring_utils.py)
  │   └─ Results aggregation
  │
  ├─ Finding processing (findings_processor.py)
  │   ├─ Deduplication (by fingerprint + account)
  │   ├─ Ranking (by impact and severity)
  │   └─ Top actions extraction
  │
  ├─ Output emission (_emit_output in cli.py)
  │   └─ Dispatches to report/terminal.py, report/html.py, etc.
  │
  └─ History persistence (history/)
      └─ SQLite insert (atomic)
```

### Consolidated report flow

```
CLI detects multiple connections
  │
  └─ consolidated.py
      ├─ For each connection:
      │   ├─ Verify STS identity
      │   ├─ Run selected packs
      │   └─ Collect findings
      ├─ Deduplicate findings (fingerprint + account_id)
      ├─ Determine cost authority
      ├─ Merge results
      └─ Atomic history persistence (parent scan + connection metadata)
```

---

## Finding Lifecycle

```
Pack check function
  │
  ├─ Detect issue (AWS API call → analysis)
  ├─ Compute fingerprint (stable hash of pack + kind + resource)
  ├─ Build finding dict (canonical v2.0 schema)
  └─ Return finding
      │
      ├─ Orchestrator validates (required fields, types, ranges)
      ├─ Legacy adapter converts if needed (v1.0 → v2.0)
      ├─ Score impact applied
      └─ Finding stored in results
```

### Fingerprinting

Fingerprints are deterministic SHA-256 hashes (truncated to 16 hex chars):

```python
# For cost anomalies (time-sensitive):
fingerprint = sha256(f"{pack}|{kind}|{account}|{service}|{usage_type}|{iso_week}")

# For resource findings (stable):
fingerprint = sha256(f"{pack}|{kind}|{resource_id}")
```

ISO-week granularity means the same anomaly across consecutive days within one week produces one fingerprint, not five.

---

## Scoring Model

### Per-pack score

Each pack starts at 100 and deducts points per finding:

| Severity | Deduction |
|----------|-----------|
| critical | -15 |
| high | -10 |
| medium | -5 |
| low | -2 |
| info | 0 |

Score is floored at 0.

### Overall score

Weighted average of pack scores:

```
overall = sum(pack_score * pack_weight for each pack) / sum(weights for run packs)
```

### Grading

| Grade | Score Range |
|-------|-------------|
| A+ | 97–100 |
| A | 90–96 |
| B | 80–89 |
| C | 70–79 |
| D | 60–69 |
| F | 0–59 |

---

## AWS API Interaction

### Session management

Kulshan uses boto3 sessions. A single session is created per report run (or per connection in consolidated mode). Sessions are not cached across runs.

### API profiling

The `aws_runtime.py` module wraps boto3 calls with timing and counting. When `--perf` is used, a summary of API calls per service is displayed after the scan.

### Region handling

- Cost pack: always `us-east-1` (Cost Explorer is global)
- Inventory packs: scan each selected region independently
- Region auto-detection: calls `ec2:DescribeRegions` with enabled-region filter

### Error handling

API errors are caught per-check. A failing API call degrades the pack (partial results) rather than aborting the entire scan. Errors are logged and included in the `errors` field of the scan result.

---

## Parallel Execution

Kulshan uses `concurrent.futures.ThreadPoolExecutor` for:
- Multi-region scanning within a pack
- Multi-pack execution (all packs are marked parallel-safe)

Thread safety:
- Each thread gets its own boto3 client (clients are thread-safe in boto3)
- Findings are collected into thread-safe lists
- Progress reporting uses a shared Rich progress bar with locking

---

## History & Persistence

### SQLite schema

Scan history uses SQLite with the following key tables:

- `scans` — parent scan record (overall score, grade, duration, etc.)
- `scan_connections` — per-connection metadata for consolidated scans
- `findings` — individual findings linked to scans

### Atomic writes

- File outputs use tempfile + rename (atomic on POSIX and Windows)
- History persistence uses SQLite transactions (all-or-nothing)
- Consolidated scans commit parent + all connection metadata in one transaction

### Retention

History is pruned to 365 days on each write. Old scans beyond this window are automatically removed.

## Configuration Loading

Precedence (highest wins):

1. CLI options
2. Environment variables (`KULSHAN_*`)
3. Project config (`./config.toml` or `./kulshan.toml`)
4. Global config (`~/.config/kulshan/config.toml`)
5. Built-in defaults

Workspace configuration is separate and resolved via the identity registry.

---

## Schema Versioning

### Finding schema

| Version | Status | Notes |
|---------|--------|-------|
| 1.0 | Legacy | Old `tool` + `check_id` shape (auto-converted) |
| 2.0 | Current | Canonical: `pack`, `kind`, `fingerprint`, float confidence |

The `models.py` module contains version-dispatch parsers. Legacy findings (v1.0) are automatically converted to v2.0 on load.

### Workspace schema

| Version | Notes |
|---------|-------|
| 1 | Current. Supports multi-connection, payer binding |

Schema migrations are forward-only and non-destructive.

---

## Extension Points

### Adding a new pack

1. Create `src/kulshan/checks/<pack_name>/`
2. Implement a scan function that returns a list of finding dicts
3. Add the pack to `TOOL_ORDER`, `TOOL_LABELS`, `TOOL_WEIGHTS` in `orchestrator.py`
4. Create a per-check IAM policy at `iam/per-check/<pack_name>.json`
5. Add required IAM actions to the full policy

### Adding a new output format

1. Create a renderer in `src/kulshan/report/`
2. Add the format choice to the CLI `--format` option
3. Add extension-based auto-detection in `_emit_output`

### Adding an MCP tool

1. Define the tool in `src/kulshan/mcp_server/tools.py`
2. Implement the handler function
3. Register with the MCP server in `server.py`
