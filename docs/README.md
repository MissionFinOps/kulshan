# Kulshan Documentation

## For Users

| Doc | What it covers |
|-----|---------------|
| [Getting Started](getting-started.md) | Install, first run, AWS permissions, API costs |
| [CLI Reference](cli.md) | Commands, flags, output formats, redaction, extras, config |
| [Troubleshooting](troubleshooting.md) | Common errors and how to fix them |
| [IAM Policy](iam-policy.md) | Permissions, per-pack policies, verification |

## For Contributors

| Doc | What it covers |
|-----|---------------|
| [Contributing](contributing.md) | Dev setup, code style, authoring packs, testing, fixtures |
| [Architecture](architecture.md) | Internal structure, data flow, scoring, design decisions |
| [Finding Schema](finding-schema.md) | Canonical finding shape, required fields, validation rules |

## Check Packs

Each of the 10 audit dimensions has its own doc:

| Pack | Doc |
|------|-----|
| Cost | [checks/cost.md](checks/cost.md) |
| Security | [checks/security.md](checks/security.md) |
| Sweep | [checks/sweep.md](checks/sweep.md) |
| DR | [checks/dr.md](checks/dr.md) |
| Age | [checks/age.md](checks/age.md) |
| Drift | [checks/drift.md](checks/drift.md) |
| Tag | [checks/tag.md](checks/tag.md) |
| Pulse | [checks/pulse.md](checks/pulse.md) |
| Limit | [checks/limit.md](checks/limit.md) |
| Topo | [checks/topo.md](checks/topo.md) |

---

`_internal/` contains planning notes, research, and design drafts. Not product documentation.
