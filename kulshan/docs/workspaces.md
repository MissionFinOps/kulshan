# Workspaces & Multi-Environment Isolation

Kulshan v0.3.0 introduces automatic identity-based environment isolation. Each AWS identity gets its own local database, history, and findings — without manual configuration.

---

## How It Works

### Automatic onboarding

When you run `kulshan report` with valid AWS credentials, Kulshan:

1. Calls `sts:GetCallerIdentity` to identify your AWS principal
2. Canonicalizes the principal ARN (strips volatile session names from assumed roles)
3. Looks up the identity in a local registry
4. If not found, creates a new isolated environment
5. Routes all data to that environment's database

```text
✓ Created environment readonlyrole-cedar
  Using readonlyrole-cedar · account 1234…5678
```

### Identity routing

On subsequent runs, Kulshan matches your current AWS identity to an existing environment automatically. No `--workspace` flag needed.

```text
  Using readonlyrole-cedar · account 1234…5678
```

### Display names

Environments are given human-friendly display names derived from the ARN. Examples:
- `readonlyrole-cedar` (from an assumed role)
- `billingaudit-river` (from a different role)
- `alice-oak` (from an IAM user)

Rename at any time:

```bash
kulshan workspace rename ws_abc "Acme Production"
```

---

## Payer Binding

When Kulshan reads CUR data containing a `bill_payer_account_id` column, it automatically binds the environment to that payer account:

```text
✓ Bound this environment to payer XXXX-XXXX-9999 using CUR evidence.
```

### What binding means

- The environment is permanently associated with a specific payer account
- Future CUR imports must match the bound payer (mismatches are rejected)
- Enables reconciliation with other environments accessing the same payer

### Binding sources

| Source | When |
|--------|------|
| CUR evidence | CUR Parquet contains `bill_payer_account_id` |
| Manual | `kulshan workspace create --payer-account` |

---

## Reconciliation

When multiple AWS identities access the same payer account, you can link their environments:

```bash
kulshan workspace reconcile
```

Reconciliation:
- Detects environments with the same payer account
- Offers to link them (never merges automatically)
- After linking, `kulshan history` shows a unified timeline
- Superseded environments become read-only references

### Example

```text
  This payer is already known.
  Existing environment: billingaudit-river

  Link this identity to billingaudit-river? [y/N]
```

If you decline, environments remain separate. You can reconcile later.

---

## Consolidated Reports

When a workspace has multiple approved connections (e.g., billing + audit), `kulshan report` produces a single consolidated report:

```bash
kulshan report
```

Output:

```text
  Consolidated report · 2 connections · Acme Production

  Report status: Complete
  Payer cost coverage: Verified payer-wide
  Connections: billing, audit
  Accounts verified: XXXX-XXXX-1111, XXXX-XXXX-2222
```

### How consolidation works

1. Each connection is executed independently
2. Findings are collected across all connections
3. Duplicate findings (same fingerprint + account) are deduplicated
4. Findings on different accounts are kept separate
5. Results are merged into one report with per-connection metadata

### Cost authority

Payer-wide Cost Explorer data is only sourced from:
- A connection whose session account matches the verified payer, OR
- An explicitly configured `cost_connection`

Arbitrary member accounts are never labeled "payer-wide."

### Running a single connection

```bash
kulshan --connection audit report
```

---

## Workspace Commands

### List environments

```bash
kulshan workspace list
```

Shows all local environments with their display names, bound payer accounts, and connection counts.

### Show current environment

```bash
kulshan workspace show
```

Displays the current environment's configuration, connections, binding status, and history summary.

### Create a workspace manually

```bash
kulshan workspace create customer-a \
  --profile customer-a-finops \
  --payer-account 999999999999
```

### Add connections

```bash
kulshan workspace connection add customer-a \
  --name audit \
  --profile customer-a-audit \
  --role-arn arn:aws:iam::999999999999:role/KulshanAudit
```

### Set default connection

```bash
kulshan workspace default-connection customer-a audit
```

### Rename

```bash
kulshan workspace rename ws_abc "Acme Production"
```

### Switch active workspace

```bash
kulshan workspace use ws_abc
```

### Reconcile

```bash
kulshan workspace reconcile
```

---

## History

History is workspace-scoped. Each environment maintains its own scan history.

```bash
# All history (including linked environments)
kulshan history

# Only scans from this workspace
kulshan history --direct-only

# Filter by credential account
kulshan history --account 123456789012
```

### Federated history

After reconciliation, `kulshan history` shows scans from all linked environments in a unified timeline. Use `--direct-only` to see only scans stored directly in the current workspace.

---

## Identity Key Versioning

| Version | Key Format | Notes |
|---------|-----------|-------|
| v1 | Profile name | Legacy (still supported for lookup) |
| v2 | Account + canonical principal ARN | Current default |

v2 keys solve the problem of volatile session names in assumed-role ARNs creating new workspaces on every login.

### Migration

- Old v1 registry entries are automatically migrated on first lookup
- Existing workspaces are preserved unchanged
- Both v1 and v2 keys are stored in the registry for backward compatibility

---

## Schema Migration

New workspace features (payer binding, scan connections) require schema additions:

| Addition | When | Impact |
|----------|------|--------|
| `scan_connections` table | First database open | Non-destructive |
| `scans.payer_account_id` column | First database open | Non-destructive |
| `scans.report_status` column | First database open | Non-destructive |

All migrations are automatic and non-destructive. No user action required.

---

## Data Layout

```
~/.local/share/kulshan/
├── registry.toml              # Identity → workspace mapping
├── workspaces/
│   ├── ws_a1b2c3d4/
│   │   ├── config.toml        # Workspace configuration
│   │   └── history.db         # SQLite scan history
│   ├── ws_e5f6g7h8/
│   │   ├── config.toml
│   │   └── history.db
│   └── default/
│       ├── config.toml
│       └── history.db
```

---

## Behavioral Notes

- Running `kulshan report` without `--workspace` auto-onboards if AWS credentials are available
- Use `--workspace default` to force legacy behavior (unbound default workspace)
- Existing manually created workspaces continue to work unchanged
- The `default` workspace remains unbound for backward compatibility
- Reconciliation is optional and never automatic
- Payer binding is permanent (cannot be unbound without deleting the workspace)
