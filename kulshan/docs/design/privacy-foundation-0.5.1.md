# Kulshan 0.5.1 Privacy Foundation

**Status:** Approved implementation plan (all corrections applied 2026-08-17)
**Release target:** 0.5.1
**Predecessor:** 0.5.0 (Reckoner query engine)
**Successor:** 0.6.0 (Consultant Export), 0.7.0 (Evidence-rich checks)
**Audited commit:** `770cad6a`

---

## Table of Contents

1. Executive summary
2. Current-state verified audit
3. Threat model
4. Trust boundaries
5. Output/persistence surface matrix
6. Identifier taxonomy
7. Canonicalization rules
8. Alias/HMAC design
9. Workspace secret lifecycle
10. Policy architecture
11. Existing redact.py migration strategy
12. CLI behavior
13. Structured stdout/TTY behavior
14. CSV defect fix
15. MCP/history/log/exception decisions
16. CUR-future compatibility
17. Tag handling
18. IAM Gate A design
19. IAM Gate B design
20. Full current IAM Allow inventory
21. Privacy terminology/claims
22. Performance constraints
23. Backward compatibility
24. Complete test matrix
25. Concrete file-by-file implementation plan
26. PR/commit sequencing
27. Risk register
28. Explicit non-goals
29. Acceptance criteria for 0.5.1
30. What 0.6.0 consultant export reuses
31. Deferred but important
32. What could make this architecture wrong?
33. Final recommendation

---

## Locked Decisions

These are constraints inherited from product/architecture review. They are not negotiable within this plan.

- ONE pseudonymization engine. No separate ConsultantAnonymizer, no parallel redaction systems.
- Dedicated RANDOM workspace secret for HMAC. Not derived from account/payer/workspace identifiers.
- HMAC-derived stable aliases with 16-hex-character tokens (e.g. `acct_7f31c2a9102d774b`). No discovery-order counters.
- Canonicalization BEFORE HMAC. Same semantic identity produces same alias regardless of surface form.
- V1 determinism within one workspace only. No cross-machine key sync.
- Interactive TTY may show real identifiers. Structured/file output pseudonymizes by default.
- Future consultant export (0.6.0) always pseudonymized, no bypass.
- `redact.py` stays temporarily during migration, deleted only after all paths have equivalent coverage.
- No consultant export implementation in 0.5.1.
- No OptScale-inspired checks in 0.5.1.

---

## 1. Executive Summary

Kulshan 0.5.1 establishes a single coherent privacy/pseudonymization layer that protects customer-identifying data at every output boundary where information could leave the local interactive context.

The release delivers:

- A `PseudonymizationEngine` backed by workspace-scoped HMAC secrets, supporting multiple policy modes (normal, persistence, future-consultant-strict).
- Canonicalization logic ensuring the same AWS identity maps to the same alias regardless of whether it appears as a bare ID, an ARN, or a CUR column value.
- Migration of all six output paths (report, Reckoner, analyze, MCP, history, exceptions) from the current partial-masking `redact.py` to the new engine.
- An immediate fix for the CSV redaction gap (security defect).
- IAM Gate A: CI validation of every policy action against a vendored AWS Service Authorization Reference snapshot.
- IAM Gate B: Per-module `REQUIRED_ACTIONS` declarations verified against the published policy.
- A `--show-identifiers` flag replacing the current `--show-pii` (with deprecated alias).
- Foundation primitives (column classification, EvidenceScope, tag-value handling) designed for reuse by 0.6.0 consultant export without requiring a second privacy system.

Total scope: ~14 PRs across 5 phases, each independently mergeable with defined stopping gates.

---

## 2. Current-State Verified Audit

Verified against commit `770cad6a` on branch `master`.

### Output paths and their current privacy state

| # | Path | Module | Redaction today | Gap |
|---|---|---|---|---|
| 1 | JSON file (`-o`) | `cli.py:106-121` | `redact_payload()` applied | None for file output |
| 2 | JSON stdout (no `-o`) | `cli.py:117-121` | **NOT applied** | Raw identifiers in piped/redirected JSON |
| 3 | HTML file | `cli.py:129-141` | `redact_account_id()` + `redact_payload()` | None |
| 4 | SARIF file | `cli.py:93-99` | `redact_payload()` on findings + account | None |
| 5 | CSV file/stdout | `cli.py:85-91` | **NONE** | `findings_to_csv()` receives raw findings |
| 6 | Terminal | `report/terminal.py` | **Explicitly exempt** (docstring line 3) | By design, but creates screenshot/share risk |
| 7 | Reckoner JSON/CSV/MD | `reckoner/renderers.py` | **NONE** | Raw account IDs in GROUP BY results |
| 8 | Reckoner terminal | `reckoner/terminal.py` | **NONE** | Same |
| 9 | Analyze JSON/MD | `analyze/export.py` | **NONE** | DeltaRow.name, OwnerCandidate.account_id raw |
| 10 | Analyze terminal | `analyze/export.py` | **NONE** | Same |
| 11 | MCP tool responses | `mcp_server/tools.py` | **NONE** | `_execute_preflight()` returns raw account+ARN; `_compact_finding()` passes raw titles |
| 12 | History SQLite | `history/__init__.py` | **NONE** | Raw account_id, payer_account_id, role_arn, full_result_json stored |
| 13 | Exception messages | `workspace/errors.py`, `workspace/sts.py` | **NONE** | Raw account IDs interpolated into error strings |
| 14 | Log output | Various | **NONE** | `payer_binding.py` logs raw payer_account_id at INFO; `onboarding.py` logs account IDs |

### Confirmed security defects

1. **CSV export gap** (`cli.py:85-91`): `findings_to_csv(all_findings)` called without `redact_payload()`. The `resource_id`, `title`, and `remediation_snippet` columns contain raw ARNs, account IDs, and resource identifiers.

2. **JSON stdout gap** (`cli.py:117-121`): When `output` is None (stdout), the JSON payload skips `redact_payload()` regardless of `--show-pii` state.

3. **MCP preflight leak** (`mcp_server/tools.py:164-166`): `_execute_preflight()` returns `{"account": identity["Account"], "arn": identity["Arn"]}` to the MCP client with zero transformation.

### Current `redact.py` capability

- 230 lines, fully implemented, zero test coverage at HEAD (tests deleted in commit `0599472e`).
- Covers: 12-digit account IDs (last-4-digit masking), ARN account portions, emails, IPs, S3 buckets, hostnames, access keys.
- Does NOT cover: tag values, cost category names, DeltaRow.name values, Reckoner output, MCP output, analyze output, CSV export.
- Masking approach: `XXXX-XXXX-9012` style. Deterministic but not pseudonymized. Two accounts ending in same 4 digits produce identical masked values, collapsing grouping.

---

## 3. Threat Model

### Adversaries

| Actor | Goal | Relevant surface |
|---|---|---|
| Accidental sharing | User shares report file/screenshot without realizing it contains customer identifiers | All file exports, terminal screenshots, MCP responses forwarded to clients |
| External consultant | Receives exported data that was intended to be anonymized but contains residual identifiers | Future 0.6.0 surface (but foundations built here) |
| Compromised MCP client | MCP client exfiltrates data returned by tools | MCP tool responses |
| Log aggregation | Central logging system collects Kulshan debug output containing identifiers | Logger calls, exception messages |
| Backup exposure | Workspace backup (git, cloud sync) exposes secret or mapping material | Workspace secret file, history database |

### Assets protected

- AWS account IDs (12-digit)
- Resource IDs (EC2, EBS, S3, Lambda, RDS, etc.)
- ARNs (full)
- Email addresses (IAM users, tag values)
- IP addresses (EIP, private IPs in findings)
- S3 bucket names
- Hostnames/endpoints
- Tag values (team names, project names, owner contacts)
- Savings Plan and Reserved Instance ARNs
- Invoice IDs

### Assets NOT protected (intentionally)

- AWS service names (AmazonEC2, AmazonS3)
- AWS region codes (us-east-1)
- Availability zone identifiers (us-east-1a)
- Usage type strings (BoxUsage:m5.xlarge)
- Cost/dollar amounts
- Dates and time periods
- Severity levels, scores, grades
- Pack names, check IDs
- Kulshan version strings

---

## 4. Trust Boundaries

```
+----------------------------------------------------------+
|  CUSTOMER LOCAL MACHINE                                   |
|                                                           |
|  +------------------+     +----------------------------+ |
|  | Interactive TTY   |     | Workspace data dir         | |
|  | (real identifiers |     | - history.db               | |
|  |  visible)         |     | - workspace.toml           | |
|  +------------------+     | - pseudonym.key (SECRET)   | |
|                            +----------------------------+ |
|                                                           |
|  +------------------+     +----------------------------+ |
|  | AWS APIs          |     | Structured output files    | |
|  | (read-only)       |     | - JSON, CSV, HTML, SARIF   | |
|  +------------------+     | - pseudonymized by default | |
|                            +----------------------------+ |
|                                                           |
|  +------------------+     +----------------------------+ |
|  | MCP client        |     | Future consultant ZIP      | |
|  | (potentially      |     | (always pseudonymized,     | |
|  |  external)        |     |  no bypass)                | |
|  +------------------+     +----------------------------+ |
+----------------------------------------------------------+

TRUST BOUNDARY: anything that crosses the "could be shared" line
must be pseudonymized by default.
```

Local-only surfaces (history SQLite, workspace TOML) remain raw because:
1. They are in platform-specific restricted-permission directories (chmod 0o600/0o700).
2. They are required for functional operations (history delta comparison uses raw account_id as lookup key).
3. They never leave the customer machine in normal operation.

The ONE exception: `full_result_json` in history SQLite is functionally an exportable report stored at rest. It must be pseudonymized before storage.

---

## 5. Output/Persistence Surface Matrix

| Surface | Contains identifiers | Leaves local context | Functional need for raw | 0.5.1 action |
|---|---|---|---|---|
| Terminal (TTY) | Yes | Unlikely (screenshots possible) | Yes (diagnostics) | Real by default; pseudonymized if non-TTY |
| JSON file (`-o`) | Yes | Likely (shared) | No | Pseudonymize (already partially done) |
| JSON stdout | Yes | Likely (piped/redirected) | No | Pseudonymize |
| CSV file/stdout | Yes | Likely | No | Pseudonymize (fix gap) |
| HTML file | Yes | Likely | No | Pseudonymize (already partially done) |
| SARIF file | Yes | Likely (CI integration) | No | Pseudonymize (already partially done) |
| Reckoner JSON/CSV/MD | Yes | Likely (saved to files) | No | Pseudonymize |
| Reckoner terminal | Yes | Unlikely | Yes | Real if TTY; pseudo if non-TTY |
| Analyze JSON/MD | Yes | Likely | No | Pseudonymize |
| Analyze terminal | Yes | Unlikely | Yes | Real if TTY; pseudo if non-TTY |
| MCP responses | Yes | Likely (external client) | No | Pseudonymize |
| History SQLite (summary) | Yes (account_id, payer) | No (local 0o600) | Yes (delta lookup) | Keep raw |
| History SQLite (full_result_json) | Yes | Possible (export) | No | Pseudonymize before storage |
| Workspace TOML | Yes (expected_session_account_id) | No (local) | Yes (verification) | Keep raw |
| Exception messages | Yes | Possible (logs, crash reports) | No | Pseudonymize via SensitiveId (scoped) |
| Logger output | Minimal (payer_binding.py, onboarding.py) | Possible (log aggregation) | No | Fix specific call sites |
| Temp files (.tmp during atomic write) | Yes (transient) | No (cleaned up) | N/A | Acceptable risk (existing behavior) |
| Workspace pseudonym.key | SECRET | No (local 0o600) | Yes | Create, protect, never export |



---

## 6. Identifier Taxonomy

| Class | Pattern/shape | Source modules | Frequency in output | Sensitivity |
|---|---|---|---|---|
| AWS account ID | `\d{12}` | session.py, adapter.py, CUR columns, CE dimensions | Every scan | High |
| Payer/management account | `\d{12}` | payer_binding.py, workspace config, CUR `bill_payer_account_id` | Per workspace | High |
| EC2 instance ID | `i-[0-9a-f]{8,17}` | findings, CUR `line_item_resource_id` | Common | High |
| EBS volume ID | `vol-[0-9a-f]{8,17}` | findings, CUR | Common | High |
| EBS snapshot ID | `snap-[0-9a-f]{8,17}` | findings | Moderate | High |
| AMI ID | `ami-[0-9a-f]{8,17}` | findings (age pack) | Moderate | Medium |
| ENI ID | `eni-[0-9a-f]{8,17}` | findings (security/topo) | Moderate | Medium |
| EIP allocation ID | `eipalloc-[0-9a-f]{8,17}` | findings (sweep) | Low | Medium |
| Generic ARN | `arn:aws[^:]*:...` | findings.resource_arn, CUR, remediation snippets | Very common | High |
| Savings Plan ARN | `arn:aws:savingsplans:...` | CUR `savings_plan_savings_plan_a_r_n`, Reckoner | Low-moderate | High |
| RI ARN | `arn:aws:ec2:...:reserved-instances/...` | CUR `reservation_reservation_a_r_n`, Reckoner | Low-moderate | High |
| Invoice ID | Alphanumeric, varies | CUR `bill_invoice_id` | Per billing period | Medium |
| S3 bucket name | DNS-label format | findings, CUR | Moderate | High |
| Hostname/endpoint | DNS format | findings (RDS endpoints, ELB DNS) | Moderate | Medium |
| Email address | `*@*.*` | IAM findings, tag values | Low-moderate | High |
| IP address | IPv4 dotted quad | findings (security pack EIPs, SG rules) | Common | Medium |
| Tag values | Free text | CUR tag columns, analyze TagCoverage | Common in CUR | High |
| CUR line item ID | `line_item_line_item_id` column | CUR only | Per CUR row | Low (opaque hash) |
| Access key ID | `AKIA[A-Z0-9]{16}` | IAM findings | Rare | Critical |
| Unknown free text | Arbitrary strings in titles, descriptions | Finding construction | Common | Variable |

---

## 7. Canonicalization Rules

### Principle

The same real-world AWS identity must always produce the same pseudonym alias, regardless of which surface form it appears in. Canonicalization normalizes variant representations to a single canonical input before HMAC.

### Canonical Form Table

| Identifier class | Example raw forms | Canonical form | Alias prefix | Context in canonical | Collision risk without context |
|---|---|---|---|---|---|
| AWS account ID | `123456789012`, within ARN `...::123456789012:...` | `account:123456789012` | `acct_` | None needed (globally unique) | None |
| EC2 instance | `i-0abc123`, `arn:aws:ec2:us-east-1:123:instance/i-0abc123` | `ec2-instance:i-0abc123` | `res_` | No (instance IDs globally unique within partition) | None |
| EBS volume | `vol-0fff999`, `arn:aws:ec2:region:account:volume/vol-0fff999` | `ec2-volume:vol-0fff999` | `res_` | No | None |
| EBS snapshot | `snap-0aaa111` | `ec2-snapshot:snap-0aaa111` | `res_` | No | None |
| AMI | `ami-0bbb222` | `ec2-ami:ami-0bbb222` | `res_` | No | None |
| ENI | `eni-0ccc333` | `ec2-eni:eni-0ccc333` | `res_` | No | None |
| EIP allocation | `eipalloc-0ddd444` | `ec2-eip:eipalloc-0ddd444` | `res_` | No | None |
| Generic ARN (non-extractable) | `arn:aws:lambda:us-east-1:123:function:my-func` | `arn:{service}:{region}:{acct_canonical}:{type}:{name}` | `arn_` | Full context preserved (service+region+account+type+name) | Prevents cross-service collision |
| SP ARN | `arn:aws:savingsplans::123:savingsplan/sp-abc` | `sp:sp-abc` | `sp_` | No (SP IDs are globally unique) | None |
| RI ARN | `arn:aws:ec2:region:account:reserved-instances/ri-abc` | `ri:ri-abc` | `ri_` | No | None |
| Invoice ID | `INV-12345-ABC` | `invoice:{raw_value}` | `inv_` | None | None |
| S3 bucket | `my-production-bucket` | `s3-bucket:{raw_value}` | `bucket_` | None (globally unique) | None |
| Hostname | `my-rds.abc123.us-east-1.rds.amazonaws.com` | `hostname:{raw_value}` | `host_` | None | None |
| Email | `john@example.com` | `email:{lowercase_raw}` | `user_` | None | None |
| IP address | `10.0.1.42` | `ip:{raw_value}` | `ip_` | None | None |
| Tag value | arbitrary | `tag-value:{raw_value}` | `tag_` | None | None |
| CUR line item ID | `abc123def456...` (opaque hash) | No pseudonymization needed | N/A | N/A | N/A (not customer-identifying) |
| Unknown/unclassified | arbitrary string matching identifier patterns | `unknown:{raw_value}` | `id_` | None | None |

### Key Canonicalization Decisions

1. **Identifier-class-aware ARN decomposition**: Each identifier class has its own canonicalizer that determines whether an ARN can be reduced to a bare ID. There is NO generic `strip_arn_to_resource_id()` helper. A class-specific canonicalizer must PROVE that the bare form and the ARN form represent the same semantic AWS identity before collapsing them.

2. **EC2 instance example**: `i-0abc123` and `arn:aws:ec2:us-east-1:123:instance/i-0abc123` canonicalize to the same resource identity ONLY because the EC2 instance canonicalizer knows that instance IDs are globally unique within a partition. The account and region in the ARN are not needed to disambiguate.

3. **Account IDs in ARNs**: The account portion of an ARN is canonicalized separately as an account ID. The ARN alias composition references the account's alias rather than re-hashing. This ensures the `acct_7f31c2a9102d774b` in an ARN alias matches the standalone account alias.

4. **Non-extractable ARNs (generic)**: For ARNs where the resource portion is not a recognized identifier pattern (e.g., Lambda function names, custom resource names), the full ARN structure (partition + service + region + account-alias + resource-type + resource-name) is preserved in the canonical form. The account portion is separately pseudonymized. The resource name portion gets its own alias scoped to the full context.

5. **Context preservation rules per class**:
   - Account ID: no context needed (globally unique 12-digit)
   - EC2/EBS/ENI resource IDs: no additional context needed (globally unique `i-`, `vol-`, `eni-` prefixed)
   - S3 bucket names: no context needed (globally unique DNS names)
   - SP/RI IDs: no context needed (globally unique within partition)
   - Lambda function name: NEEDS service + account + region context (names are account-scoped)
   - Generic resource names: NEEDS full ARN context
   - Hostnames: no context needed (unique strings)
   - Emails: no context needed (unique strings, lowercased)

6. **Case sensitivity**: Account IDs, resource IDs, and ARNs are case-sensitive (AWS preserves case). Emails are lowercased before canonicalization. Hostnames are lowercased.

7. **CUR line item IDs**: The `line_item_line_item_id` column contains AWS-generated opaque hashes. These are NOT customer-identifying and are classified as PASSTHROUGH (not pseudonymized).

8. **Tests must prove BOTH directions**:
   - Semantically equivalent forms produce the same alias (e.g., bare instance ID and its ARN)
   - Superficially similar but semantically different identifiers do NOT collapse (e.g., same resource name under different services)

---

## 8. Alias/HMAC Design

### Derivation

```
alias = prefix + "_" + hex(HMAC-SHA256(workspace_secret, canonical_form))[:16]
```

- **Hash function**: HMAC-SHA256.
- **Key**: 32-byte random workspace secret.
- **Input**: Canonical form string (UTF-8 encoded).
- **Output**: First 16 hex characters (64 bits) of the HMAC digest, prefixed by identifier class.
- **Collision probability**: With 16 hex chars (64 bits), collision probability reaches 1% at approximately 600 million distinct values per prefix class. Effectively zero risk for any practical Kulshan workload.

### Composite aliases

For ARNs containing multiple identity components:

```
arn:aws:ec2:us-east-1:123456789012:instance/i-0abc123
```

Becomes:

```
arn:aws:ec2:us-east-1:acct_7f31c2a9102d774b:instance/res_a72f192cc508bd81
```

The account and resource portions are individually pseudonymized using their own canonical forms, then reassembled into a structurally valid ARN-like string. Service, region, and resource type are AWS vocabulary (passthrough).

### Properties

- **Deterministic**: Same input + same secret = same output. Always.
- **Stateless**: No lookup table needed for generation. HMAC computes the same output every time.
- **One-way**: Cannot recover the original from the alias without the secret.
- **Workspace-scoped**: Different workspaces have different secrets, so the same account ID maps to different aliases in different workspaces.
- **No ordering dependence**: Two runs produce identical aliases regardless of row/discovery order.
- **Efficient**: Single HMAC per identifier. No database lookups, no sequential counters, no global state.
- **Fixed length**: Alias token is ALWAYS exactly 16 lowercase hexadecimal characters. No variable-length collision repair.

### Customer-side label file (optional, future)

A customer may later create `{workspace_dir}/pseudonym-labels.toml`:

```toml
[labels]
"acct_7f31c2a9102d774b" = "Production-Payments"
"res_a72f192cc508bd81" = "Main API server"
```

This is purely a local convenience for re-identification. It is NEVER included in any export. It is not required for deterministic alias generation. Not implemented in 0.5.1.

---

## 9. Workspace Secret Lifecycle

### Generation

- Created on first pseudonymized output if absent.
- 32 bytes from `os.urandom(32)`.
- Stored as raw binary in `{workspace_dir}/pseudonym.key`.

### Storage

- **Location**: Inside the workspace data directory (e.g., `~/.local/share/Kulshan/missionfinops/ws_7f3a842c/pseudonym.key`).
- **Permissions**: Created with mode `0o600` (owner read/write only). On Windows, inherits parent directory ACL (already restricted by platformdirs user_data_dir).
- **Format**: Raw 32-byte binary file. No encoding, no wrapper. Minimizes parsing surface.

### Rotation

- No automatic rotation. The secret is stable for the lifetime of the workspace.
- Manual rotation: delete the file. Next pseudonymized output creates a new secret. All aliases change. This is intentional and documented.
- There is no "rotate in place" operation. Rotation means accepting that previous reports cannot be correlated with future reports by alias alone.

### Deletion

- Deleting the secret file causes a fresh secret to be generated on next use. All prior aliases become orphaned.
- This is acceptable because: (a) the local customer can still look at their real identifiers with `--show-identifiers`, (b) there is no external system depending on alias stability.

### Workspace cloning/migration

- If a workspace is cloned (directory copied), the secret goes with it. Aliases remain stable in the clone.
- If a workspace is migrated (existing workspace/migration.py path), the secret file is included in the migration.

### Backup behavior

- The secret lives alongside other workspace state. If the workspace is backed up, the secret is backed up.
- This is acceptable: the workspace already contains `expected_session_account_id` and `payer_account_id` in plaintext TOML. The secret does not increase the sensitivity of the workspace directory.

### Loss tolerance

- Loss of the secret means loss of alias stability across reports. It does NOT mean loss of data or functionality.
- New secret = new aliases. Old pseudonymized reports retain their aliases but cannot be correlated to new ones by alias value.

### Concurrency/process safety

- **Atomic creation**: Use `os.open(path, O_CREAT | O_EXCL | O_WRONLY)` to create atomically. If two processes race, one wins, one gets `FileExistsError` and reads the winner's file.
- **No writes after creation**: The file is written once and never modified. No locking needed for reads.

### Corruption recovery

- If the file exists but is not exactly 32 bytes: treat as corrupt.
- **FAIL CLOSED**: pseudonymization fails. No pseudonymized output is produced. Error message tells the user the secret is corrupt and how to deliberately reset:
  ```
  ERROR: Workspace pseudonymization secret is corrupt ({path}).
  To reset (this will change all future aliases): delete the file and re-run.
  ```
- The user must consciously accept alias reset by deleting the file themselves.
- Silent regeneration is NOT acceptable because it would change all aliases without the user's awareness.

### Export prohibition

- The secret MUST NEVER appear in any output file, log, exception, MCP response, or report.
- The engine loads the secret into memory and never serializes it back to any output path.
- Tests will assert this.

---

## 10. Policy Architecture

### Engine structure

```python
class PseudonymizationEngine:
    """Single pseudonymization engine for all Kulshan output paths."""

    def __init__(self, secret: bytes, policy: PseudonymPolicy):
        self._secret = secret
        self._policy = policy

    def pseudonymize_value(self, value: str, identifier_class: IdentifierClass) -> str:
        """Canonicalize + HMAC + format a single identifier."""

    def pseudonymize_payload(self, payload: Any) -> Any:
        """Deep-walk a JSON-serializable structure, classifying and pseudonymizing fields."""

    def pseudonymize_text(self, text: str) -> str:
        """Scan free text for embedded identifiers and replace them."""

    def is_active(self) -> bool:
        """Whether pseudonymization should be applied in current context."""
```

### Policy modes

```python
@dataclass(frozen=True)
class PseudonymPolicy:
    mode: str  # "normal", "persistence", "consultant" (future)
    tty_bypass: bool  # True = skip pseudonymization when stdout is a TTY
    show_identifiers_override: bool  # True = user passed --show-identifiers
```

| Policy | tty_bypass | Applies to |
|---|---|---|
| normal | True | `kulshan report`, `kulshan analyze`, Reckoner interactive |
| persistence | False | History `full_result_json`, MCP responses |
| consultant (future) | False | `kulshan export consultant` (0.6.0) |

### Context creation

```python
def create_pseudonym_context(
    workspace_path: Path | None,
    show_identifiers: bool = False,
) -> PseudonymizationEngine | None:
    """Load or create workspace secret, build engine with normal policy.

    Returns None if show_identifiers=True (bypass).
    """
```

The engine is created once per CLI invocation and threaded through to all output paths. It is NOT a global singleton. It is passed explicitly.

### Field classification

The engine uses a `FieldClassifier` that maps field names and value patterns to identifier classes:

```python
class FieldClassifier:
    """Classify a (key, value) pair into an IdentifierClass or PASSTHROUGH."""

    # Field-name rules (fast path)
    ACCOUNT_FIELDS = {"account_id", "account", "accountid", "payer_account_id", ...}
    ARN_FIELDS = {"resource_arn", "arn", ...}
    # ...

    # Pattern rules (for free text scanning)
    PATTERNS = [
        (re.compile(r'\b\d{12}\b'), IdentifierClass.ACCOUNT),
        (re.compile(r'\barn:aws[^:]*:...'), IdentifierClass.ARN),
        # ...
    ]
```

This is an evolution of `redact.py`'s field classification sets (`_ACCOUNT_FIELDS`, `_ARN_FIELDS`, etc.) but with identifier-class-aware output rather than generic masking.



---

## 11. Existing redact.py Migration Strategy

### Disposition

`redact.py` is NOT deleted in 0.5.1 until the final cleanup PR. The migration is path-by-path:

| PR | Path migrated | redact.py function replaced | New engine function |
|---|---|---|---|
| Phase 2 PR | JSON/HTML/SARIF/CSV file exports | `redact_payload()`, `redact_account_id()`, `redact_filename()` | `engine.pseudonymize_payload()` |
| Phase 2 PR | Reckoner renderers | (none existed) | `engine.pseudonymize_payload()` on QueryResult rows |
| Phase 2 PR | Analyze export | (none existed) | `engine.pseudonymize_payload()` on brief fields |
| Phase 2 PR | MCP tools | (none existed) | `engine.pseudonymize_payload()` on response dicts |
| Phase 2 PR | History persistence | (none existed) | `engine.pseudonymize_payload()` on full_result_json |
| Cleanup PR | Delete redact.py | All remaining references | Remove file, update imports |

### Coexistence rule

During migration, a single output path uses EITHER `redact.py` OR the new engine. Never both on the same path simultaneously. The migration replaces the `redact_payload()` call site with the new engine call. The two systems do not compose.

### Standalone helpers retained

`redact_filename()` logic (stripping account IDs from default filenames) moves into the engine as a utility. The function signature is preserved for backward compatibility during migration.

---

## 12. CLI Behavior

### Flag change

| Current | New | Behavior |
|---|---|---|
| `--show-pii` | `--show-identifiers` | Disable pseudonymization for this invocation |
| (none) | `--show-pii` (hidden deprecated alias) | Maps to `--show-identifiers` internally |

The flag is added to the `report`, `analyze`, Reckoner, and `convert` commands. It is NOT added to future `export consultant` (0.6.0).

### Deprecation

When `--show-pii` is used, a one-line stderr warning is emitted:
```
warning: --show-pii is deprecated, use --show-identifiers
```

No breakage. The flag continues to work.

### Default behavior by command

| Command | Default (no flag) | With --show-identifiers |
|---|---|---|
| `kulshan report` | Pseudonymize structured output; real in TTY | Real everywhere |
| `kulshan report -o file.json` | Pseudonymize | Real |
| `kulshan analyze cost` | Pseudonymize structured; real in TTY | Real everywhere |
| `kulshan query run` (Reckoner) | Pseudonymize structured; real in TTY | Real everywhere |
| `kulshan history` | Pseudonymize displayed account IDs | Real |
| `kulshan preflight` | Real (diagnostic, always shows your own identity) | N/A (no privacy concern) |
| `kulshan workspace show` | Real (user-configured values) | N/A |
| `kulshan export consultant` (0.6.0) | Always pseudonymized | Flag NOT accepted |

---

## 13. Structured stdout/TTY Behavior

### Detection logic

```python
import sys

def is_interactive_tty() -> bool:
    """True if stdout is connected to a human terminal."""
    return hasattr(sys.stdout, 'isatty') and sys.stdout.isatty()
```

### Decision matrix

| Condition | Pseudonymize? |
|---|---|
| stdout is TTY + format is `terminal` (default) | NO (real identifiers) |
| stdout is TTY + format is `json` (explicit `--format json`) | YES |
| stdout is TTY + format is `csv` | YES |
| stdout is NOT TTY (piped/redirected) + any format | YES |
| Output goes to file (`-o`) | YES |
| `--show-identifiers` passed | NO (regardless of above) |

### Rationale

- `--format json` is an explicit signal that output is structured/shareable even when typed in a terminal. Pseudonymize.
- Default terminal rendering (Rich tables) is for the local human. Real identifiers are useful.
- Piped output (`kulshan report | jq .`) loses TTY status. Pseudonymize because the pipe target is unknown.
- `kulshan report > file.json` also loses TTY status. Pseudonymize.

### Rich Console interaction

Rich's `Console()` already detects whether it's writing to a terminal. The pseudonymization decision is made BEFORE rendering, not during. The engine either transforms the payload or passes it through; the renderer sees the final form.

---

## 14. CSV Defect Fix

### Bug

`cli.py:85-91`:
```python
if fmt == "csv":
    from kulshan.report.csv_export import findings_to_csv
    csv_str = findings_to_csv(all_findings)  # RAW findings, no redaction
```

### Fix (immediate, Phase 0)

```python
if fmt == "csv":
    from kulshan.report.csv_export import findings_to_csv
    export_findings = all_findings if show_pii else redact_payload(all_findings)
    csv_str = findings_to_csv(export_findings)
```

This uses the existing `redact_payload()` as a stopgap. When the full engine lands (Phase 2), this call site migrates to the engine like all other paths.

### Test

```python
def test_csv_export_does_not_contain_raw_account_id():
    """CSV output must not contain raw 12-digit account IDs when show_pii=False."""
```

---

## 15. MCP/History/Log/Exception Decisions

### MCP tool responses

**Decision: Pseudonymize all MCP responses in 0.5.1.**

- `_execute_preflight()`: Return pseudonymized account and ARN. The MCP client does not need the real account ID to verify connectivity.
- `_compact_finding()`: Titles, recommendations, and resource references are pseudonymized.
- `_execute_analyze_*()`: Brief JSON is pseudonymized.
- `_execute_report()`: Compact findings are pseudonymized.

The MCP worker subprocess loads the workspace secret from environment context (workspace path passed via argument or env var).

Exception: `kulshan_list_packs()` returns static pack descriptions. No identifiers. No pseudonymization needed.

### History SQLite

**Decision: Hybrid approach.**

| Column | Action | Rationale |
|---|---|---|
| `scans.account_id` | Keep raw | Required for `get_previous_scan()` delta lookup |
| `scans.payer_account_id` | Keep raw | Required for federated history payer matching |
| `scan_connections.session_account_id` | Keep raw | Required for connection-based filtering |
| `scan_connections.role_arn` | Keep raw | Required for workspace identity verification |
| `scans.full_result_json` | Pseudonymize before storage | This is an exportable report artifact stored at rest |
| `scan_connections.profile` | Keep raw | User-chosen string, not AWS-identifying |

### Logger calls

**Decision: Fix specific call sites rather than introducing SensitiveId everywhere.**

Identified logger calls interpolating identifiers:

| Location | Current content | Fix |
|---|---|---|
| `workspace/payer_binding.py` (via onboarding) | Logs raw `payer_account_id` at INFO | Replace with masked version (`***...{last4}`) in log message |
| `workspace/onboarding.py:386-388` | Logs `display_name`, identity key, account_id | Replace account_id with masked |
| `workspace/onboarding.py:492-494` | Logs `payer_account_id` | Replace with masked |
| `workspace/federated_history.py:163-165` | Logs `ws_payer` and `target_payer` | Replace with masked |

Total: 4 call sites. Straightforward string change. Does not require SensitiveId type system.

### Exception messages

**Decision: Introduce SensitiveId at a LIMITED scope (3 exception classes only). Do not refactor the entire codebase.**

| Exception class | Current interpolation | Change |
|---|---|---|
| `StsVerificationError` | `f"expected {credential_account}, but STS returned {account_id}"` | Accept SensitiveId; `__str__` emits masked form |
| `WorkspaceCredentialMismatchError` | `f"expected account {expected_account}, got {actual_account}"` | Same |
| `InvalidPayerEvidenceError` | `f"'{value}' is not a valid..."` | Value is a failed validation; showing partial is acceptable |
| `MultiplePayerEvidenceError` | `f"({', '.join(payer_ids)})"` | Accept SensitiveId list |

### SensitiveId recommendation

**Recommendation: Implement SensitiveId in 0.5.1, but scope it to the 5 entry points that feed exception classes. Do NOT wrap every str field in the codebase.**

Justification:
- There are exactly 3 exception classes and 4 logger call sites that leak identifiers.
- A full SensitiveId refactor touching `adapter.py`, `session.py`, `workspace/config.py`, and all finding construction would be an XL effort for marginal gain over fixing 7 specific call sites.
- The risk of accidental leaks via new exception classes is LOW because exception handling is concentrated in workspace/ module.
- Full SensitiveId wrapping can be revisited in 0.7.0 if the attack surface expands.

Scope for 0.5.1:
- `SensitiveId` type exists in `pseudonym/types.py`.
- `session.py:get_account_id()` wraps return value.
- `workspace/sts.py` verify functions return `SensitiveId` for account_id.
- 3 exception classes accept `SensitiveId` parameters.
- `SensitiveId.__str__()` returns `"***{last4}"` (not the full pseudonym alias, because exceptions are diagnostic, not report output).
- `SensitiveId.raw` property available for internal logic that needs the real value.

---

## 16. CUR-Future Compatibility

### Column classification system (architecture built in 0.5.1, comprehensive registry deferred to 0.6.0)

0.5.1 builds the REUSABLE PRIMITIVES for column classification. It does NOT exhaustively classify all CUR 2.0 columns.

The classification enum and API are created:

```python
class ColumnClassification(Enum):
    PASSTHROUGH = "passthrough"
    PSEUDONYMIZE = "pseudonymize"
    TRANSFORM_TAG = "transform_tag"
    DROP = "drop"
    UNCLASSIFIED = "unclassified"
```

A small representative test fixture demonstrates the API with ~10-15 example columns. This proves the architecture is reusable by 0.6.0.

### Classification categories (architecture, for future use)

| Category | Meaning | Future consultant behavior |
|---|---|---|
| `passthrough` | Value is safe (costs, dates, service names, regions, usage types) | Preserved as-is |
| `pseudonymize` | Value is a customer identifier | HMAC alias applied |
| `transform_tag` | Tag value; pseudonymized by default, `--keep-tag` can preserve | Pseudonymized unless explicitly kept |
| `drop` | Value has no analytical use and contains risk | Column removed from export |
| `unclassified` | Column not in registry | **BLOCK EXPORT** (future default) |

### What 0.6.0 adds (NOT in 0.5.1)

- Comprehensive `cur_columns.toml` with all known CUR 2.0 columns classified
- Unknown-column blocking behavior
- `--drop-unclassified-columns` flag
- Consultant manifests identifying dropped/transformed columns
- CUR privacy gates

### 0.5.1 deliverable

- `src/kulshan/pseudonym/classifier.py` with `ColumnClassification` enum and `classify_column()` function signature
- A small test fixture proving the API works
- The architecture is proven reusable; the exhaustive registry is deferred

---

## 17. Tag Handling

### Design

- **Tag keys** (e.g., `resource_tags_user_owner`): These are Kulshan's semantic labels from `cur/schema.py`. They are structural, not customer-identifying. They pass through unchanged.
- **Tag values** (e.g., `platform-team`, `john@corp.com`): These are customer-defined free text. They are pseudonymized by default.

### Future `--keep-tag` behavior (0.6.0)

```bash
kulshan export consultant --keep-tag environment --keep-tag region_tag
```

- Exempts listed tag keys from default pseudonymization.
- Retained values STILL pass through the privacy validator (Gate 3 in 0.6.0).
- A retained value like `environment=production` passes.
- A retained value like `owner=john.smith@bank.com` is caught by the residual identifier scan and blocks export.

### 0.5.1 deliverable

- The `FieldClassifier` in the pseudonymization engine knows that fields matching `resource_tags_*` patterns have their VALUES pseudonymized.
- The `CUR_COLUMNS.toml` registry marks tag columns as `transform_tag`.
- No `--keep-tag` CLI flag in 0.5.1 (that's 0.6.0 consultant export).

---

## 18. IAM Gate A Design

### Purpose

Validate every action in `iam/kulshan-readonly.json` against AWS's official machine-readable Service Authorization Reference.

### Data source

AWS publishes:
- Service list: `https://servicereference.us-east-1.amazonaws.com/v1/service-list.json`
- Per-service reference: `https://servicereference.us-east-1.amazonaws.com/v1/{prefix}/{prefix}.json`

### Vendored snapshot

**Location:** `iam/aws-service-reference/`
```
iam/aws-service-reference/
    snapshot-metadata.json     # timestamp, source URL, hash
    service-list.json          # cached service list
    services/                  # per-service JSON files
        access-analyzer.json
        acm.json
        ...
```

**Metadata format:**
```json
{
  "retrieved_at": "2026-08-17T00:00:00Z",
  "source_url": "https://servicereference.us-east-1.amazonaws.com/v1/service-list.json",
  "sha256_service_list": "abc123...",
  "service_count": 30,
  "note": "Vendored for offline CI. Refresh with: python iam/refresh_service_reference.py"
}
```

### Refresh mechanism

A script `iam/refresh_service_reference.py`:
1. Fetches the service list.
2. For each service prefix used in Kulshan's policy, fetches the per-service JSON.
3. Writes to `iam/aws-service-reference/`.
4. Updates `snapshot-metadata.json`.
5. Run manually by maintainer before release. NOT run in CI.

### CI validation logic

Test: `tests/unit/test_iam_gate_a.py`

```python
def test_all_policy_actions_valid():
    """Every action in kulshan-readonly.json must be VALID or UNVALIDATABLE."""
    for action in policy_actions:
        prefix, name = action.split(":", 1)
        service_ref = load_service_reference(prefix)
        if service_ref is None:
            results.append((action, "UNVALIDATABLE_PREFIX"))
        elif name in service_ref["actions"]:
            results.append((action, "VALID"))
        else:
            results.append((action, "INVALID_ACTION"))

    invalid = [r for r in results if r[1] == "INVALID_ACTION"]
    assert not invalid, f"Invalid actions: {invalid}"

    unvalidatable = [r for r in results if r[1] == "UNVALIDATABLE_PREFIX"]
    # Report but do not fail for unvalidatable
    if unvalidatable:
        warnings.warn(f"Unvalidatable prefixes: {unvalidatable}")
```

### Three possible states

| State | Meaning | CI behavior |
|---|---|---|
| `VALID` | Action exists in the AWS service reference | Pass |
| `INVALID_ACTION` | Prefix exists but action name not found | **FAIL** |
| `UNVALIDATABLE_PREFIX` | Service prefix not in vendored snapshot | **WARN** (does not fail CI) |

### Stale snapshot handling

- If a service reference file is missing for a prefix in the policy, the action is `UNVALIDATABLE_PREFIX`.
- CI produces a warning listing unvalidatable prefixes.
- The `refresh_service_reference.py` script is run before each release to update.
- A test `test_snapshot_not_too_old()` warns (does not fail) if snapshot is older than 90 days.

---

## 19. IAM Gate B Design

### Purpose

Every check/module that makes AWS API calls declares its required IAM actions. CI verifies all declared actions are present in the published policy. This prevents: valid API call missing from policy causes AccessDenied causes silent false negative.

### Existing infrastructure

The repository already has `iam/registry.json` with 160+ entries mapping `iam_action` to `boto3_method`, `capability`, and `status` (required/optional). This is the authoritative registry.

The `iam/per-check/` directory has per-capability policy fragments that `compose.py` unions into the final policy.

### Gate B mechanism

**Option chosen: Extend the existing registry as authoritative.**

`iam/registry.json` already maps every action to a capability. Gate B verifies:

1. Every action with `"status": "required"` and `"baseline_eligible": true` is present in `kulshan-readonly.json`.
2. Every per-check policy file contains only actions that exist in the registry.
3. Every action in the composed policy exists in the registry.

These checks already partially exist in `test_trust_integrity.py`:
- `test_registry_required_actions_all_in_composed()` verifies registry -> policy.
- `test_no_invalid_actions_anywhere_in_iam_dir()` checks for known-bad action names.

### What 0.5.1 adds

1. **Reverse check**: Every action in composed policy must exist in registry. (Currently not tested.)
2. **Code-to-registry mapping**: A new field `"source_module"` in registry entries pointing to the scanner that uses it. Initially populated for ~50% of entries; remainder flagged as `"source_module": "unverified"`.
3. **Gate B test**: `test_iam_gate_b_policy_covers_registry()` and `test_iam_gate_b_registry_covers_policy()`.
4. **Unused action detection**: Actions in registry marked `"status": "required"` where `"source_module": "unverified"` are reported as candidates for audit.

### Retrofit scope for 0.5.1

Adding `source_module` to every registry entry is M-effort. Recommend:
- Populate for all `cost`, `security`, and `dr` capabilities (the three largest, covering ~100 of 160 actions).
- Mark remainder as `"source_module": "unverified"`.
- A CI warning (not failure) reports unverified entries.
- Full coverage target: 0.7.0.

---

## 20. Full Current IAM Allow Inventory

160 actions across 30 service prefixes. Grouped by service with analysis.

| Service | Action | Capability | Confirmed Used | Optional | Access Level | Read-Only Safe | Sensitivity | Recommendation |
|---|---|---|---|---|---|---|---|---|
| **access-analyzer** | GetAnalyzer | security | Yes | No | Read | Yes | Low | KEEP |
| | GetFinding | security | Yes | No | Read | Yes | Low | KEEP |
| | ListAnalyzers | security | Yes | No | List | Yes | Low | KEEP |
| | ListFindings | security | Yes | No | List | Yes | Medium (findings contain resource details) | KEEP |
| **acm** | DescribeCertificate | security | Yes | No | List | Yes | Low | KEEP |
| | ListCertificates | security | Yes | No | List | Yes | Low | KEEP |
| **autoscaling** | DescribeAutoScalingGroups | dr | Yes | No | List | Yes | Low | KEEP |
| **backup** | DescribeRecoveryPoint | dr | Yes | No | List | Yes | Low | KEEP |
| | ListBackupPlans | dr | Yes | No | List | Yes | Low | KEEP |
| | ListBackupVaults | dr | Yes | No | List | Yes | Low | KEEP |
| | ListProtectedResources | dr | Yes | No | List | Yes | Low | KEEP |
| | ListRecoveryPointsByBackupVault | dr | Yes | No | List | Yes | Low | KEEP |
| **bcm-data-exports** | GetExport | cost | Yes | No | Read | Yes | Medium (export config) | KEEP |
| | ListExports | cost | Yes | No | List | Yes | Low | KEEP |
| **ce** | GetAnomalies | cost | Yes | No | Read | Yes | Medium (cost data) | KEEP |
| | GetCostAndUsage | cost | Yes | No | Read | Yes | Medium (cost data) | KEEP |
| | GetCostAndUsageComparisons | cost | Yes | No | Read | Yes | Medium | KEEP |
| | GetCostAndUsageWithResources | cost | Yes | No | Read | Yes | High (resource-level cost) | KEEP |
| | GetCostComparisonDrivers | cost | Yes | No | Read | Yes | Medium | KEEP |
| | GetCostForecast | cost | Yes | No | Read | Yes | Low | KEEP |
| | GetReservationCoverage | cost | Yes | No | Read | Yes | Medium | KEEP |
| | GetReservationPurchaseRecommendation | cost | Yes | No | Read | Yes | Medium | KEEP |
| | GetReservationUtilization | cost | Yes | No | Read | Yes | Medium | KEEP |
| | GetRightsizingRecommendation | cost | Yes | No | Read | Yes | High (instance details) | KEEP |
| | GetSavingsPlansPurchaseRecommendation | cost | Yes | No | Read | Yes | Medium | KEEP |
| | GetSavingsPlansUtilization | cost | Yes | No | Read | Yes | Medium | KEEP |
| | GetTags | cost | Yes | No | Read | Yes | Medium (tag keys/values) | KEEP |
| **cloudformation** | DescribeStackDriftDetectionStatus | drift | Yes | No | List | Yes | Low | KEEP |
| | DescribeStackResourceDrifts | drift | Yes | No | List | Yes | Medium | KEEP |
| | **DetectStackDrift** | drift | Yes | No | **Write** | **SEE BELOW** | Low | **KEEP with documentation** |
| | ListStackResources | drift | Yes | No | List | Yes | Low | KEEP |
| | ListStacks | drift | Yes | No | List | Yes | Low | KEEP |
| **cloudtrail** | DescribeTrails | security | Yes | No | List | Yes | Low | KEEP |
| | GetEventSelectors | security | Yes | No | Read | Yes | Low | KEEP |
| | GetTrailStatus | security | Yes | No | Read | Yes | Low | KEEP |
| | ListTrails | security | Yes | No | List | Yes | Low | KEEP |
| **cloudwatch** | DescribeAlarms | pulse | Yes | No | List | Yes | Low | KEEP |
| | GetMetricStatistics | pulse | Yes | No | Read | Yes | Low | KEEP |
| | ListMetrics | pulse | Yes | No | List | Yes | Low | KEEP |
| **config** | DescribeConfigRules | security | Yes | No | List | Yes | Low | KEEP |
| | DescribeConfigurationRecorderStatus | security | Yes | No | List | Yes | Low | KEEP |
| | DescribeConfigurationRecorders | security | Yes | No | List | Yes | Low | KEEP |
| | DescribeDeliveryChannels | security | Yes | No | List | Yes | Low | KEEP |
| **cur** | DescribeReportDefinitions | cost | Yes | No | Read | Yes | Low | KEEP |
| **dynamodb** | DescribeContinuousBackups | dr | Yes | No | List | Yes | Low | KEEP |
| | DescribeTable | dr | Yes | No | List | Yes | Low | KEEP |
| | ListTables | dr | Yes | No | List | Yes | Low | KEEP |
| | ListTagsOfResource | dr | Yes | No | List | Yes | Medium (tag values) | KEEP |
| **ec2** | DescribeAddresses | security | Yes | No | List | Yes | Medium (EIP ownership) | KEEP |
| | DescribeAvailabilityZones | security | Yes | No | List | Yes | Low | KEEP |
| | DescribeFlowLogs | security | Yes | No | List | Yes | Low | KEEP |
| | DescribeImages | security | Yes | No | List | Yes | Low | KEEP |
| | DescribeInstances | security | Yes | No | List | Yes | High (full instance metadata) | KEEP |
| | DescribeInternetGateways | security | Yes | No | List | Yes | Low | KEEP |
| | DescribeNatGateways | security | Yes | No | List | Yes | Low | KEEP |
| | DescribeNetworkAcls | security | Yes | No | List | Yes | Low | KEEP |
| | DescribeNetworkInterfaces | security | Yes | No | List | Yes | Medium (IP info) | KEEP |
| | DescribeRegions | security | Yes | No | List | Yes | Low | KEEP |
| | DescribeRouteTables | security | Yes | No | List | Yes | Low | KEEP |
| | DescribeSecurityGroups | security | Yes | No | List | Yes | High (network rules) | KEEP |
| | DescribeSnapshotAttribute | security | Yes | No | List | Yes | Medium (sharing config) | KEEP |
| | DescribeSnapshots | security | Yes | No | List | Yes | Medium | KEEP |
| | DescribeSubnets | security | Yes | No | List | Yes | Low | KEEP |
| | DescribeTransitGatewayAttachments | security | Yes | No | List | Yes | Low | KEEP |
| | DescribeTransitGateways | security | Yes | No | List | Yes | Low | KEEP |
| | DescribeVolumes | security | Yes | No | List | Yes | Medium | KEEP |
| | DescribeVpcEndpoints | security | Yes | No | List | Yes | Low | KEEP |
| | DescribeVpcPeeringConnections | security | Yes | No | List | Yes | Medium (cross-account) | KEEP |
| | DescribeVpcs | security | Yes | No | List | Yes | Low | KEEP |
| | DescribeVpnConnections | security | Yes | No | List | Yes | Medium (VPN config) | KEEP |
| **ecr** | DescribeRepositories | sweep | Yes | No | List | Yes | Low | KEEP |
| | ListImages | sweep | Yes | No | List | Yes | Low | KEEP |
| **ecs** | DescribeClusters | sweep | Yes | No | List | Yes | Low | KEEP |
| | DescribeServices | sweep | Yes | No | List | Yes | Low | KEEP |
| | ListClusters | sweep | Yes | No | List | Yes | Low | KEEP |
| | ListServices | sweep | Yes | No | List | Yes | Low | KEEP |
| **eks** | DescribeCluster | security | Yes | No | List | Yes | Medium (cluster config) | KEEP |
| | ListClusters | security | Yes | No | List | Yes | Low | KEEP |
| **elasticache** | DescribeCacheClusters | dr | Yes | No | List | Yes | Low | KEEP |
| | DescribeReplicationGroups | dr | Yes | No | List | Yes | Low | KEEP |
| **elasticloadbalancing** | DescribeLoadBalancers | sweep | Yes | No | List | Yes | Low | KEEP |
| | DescribeTags | sweep | Yes | No | List | Yes | Medium (tag values) | KEEP |
| | DescribeTargetGroups | sweep | Yes | No | List | Yes | Low | KEEP |
| | DescribeTargetHealth | sweep | Yes | No | List | Yes | Low | KEEP |
| **guardduty** | GetDetector | security | Yes | No | Read | Yes | Low | KEEP |
| | GetFindings | security | Yes | No | Read | Yes | High (security findings) | KEEP |
| | ListDetectors | security | Yes | No | List | Yes | Low | KEEP |
| | ListFindings | security | Yes | No | List | Yes | Low | KEEP |
| **iam** | GenerateCredentialReport | security | Yes | No | Read | Yes* | Low | KEEP |
| | GenerateServiceLastAccessedDetails | security | Yes | No | Read | Yes* | Low | KEEP |
| | GetAccountAuthorizationDetails | security | Yes | No | Read | Yes | High (full IAM config) | KEEP |
| | GetAccountPasswordPolicy | security | Yes | No | Read | Yes | Low | KEEP |
| | GetAccountSummary | security | Yes | No | Read | Yes | Low | KEEP |
| | GetCredentialReport | security | Yes | No | Read | Yes | High (user credentials metadata) | KEEP |
| | GetPolicy | security | Yes | No | Read | Yes | Low | KEEP |
| | GetPolicyVersion | security | Yes | No | Read | Yes | Medium | KEEP |
| | GetRole | security | Yes | No | Read | Yes | Low | KEEP |
| | GetServiceLastAccessedDetails | security | Yes | No | Read | Yes | Medium | KEEP |
| | GetUser | security | Yes | No | Read | Yes | Medium | KEEP |
| | ListAccessKeys | security | Yes | No | List | Yes | Medium (key metadata) | KEEP |
| | ListAccountAliases | security | Yes | No | List | Yes | Low | KEEP |
| | ListAttachedGroupPolicies | security | Yes | No | List | Yes | Low | KEEP |
| | ListAttachedRolePolicies | security | Yes | No | List | Yes | Low | KEEP |
| | ListAttachedUserPolicies | security | Yes | No | List | Yes | Low | KEEP |
| | ListGroups | security | Yes | No | List | Yes | Low | KEEP |
| | ListMFADevices | security | Yes | No | List | Yes | Low | KEEP |
| | ListPolicies | security | Yes | No | List | Yes | Low | KEEP |
| | ListRoles | security | Yes | No | List | Yes | Low | KEEP |
| | ListUsers | security | Yes | No | List | Yes | Medium (usernames) | KEEP |
| | ListVirtualMFADevices | security | Yes | No | List | Yes | Low | KEEP |
| **kms** | DescribeKey | security | Yes | No | List | Yes | Low | KEEP |
| | GetKeyPolicy | security | Yes | No | Read | Yes | Medium (policy doc) | KEEP |
| | GetKeyRotationStatus | security | Yes | No | Read | Yes | Low | KEEP |
| | ListAliases | security | Yes | No | List | Yes | Low | KEEP |
| | ListKeys | security | Yes | No | List | Yes | Low | KEEP |
| **lambda** | GetAccountSettings | security | Yes | No | Read | Yes | Low | KEEP |
| | GetFunction | security | Yes | No | Read | Yes | Medium (code config) | KEEP |
| | GetFunctionConfiguration | security | Yes | No | Read | Yes | Medium | KEEP |
| | GetPolicy | security | Yes | No | Read | Yes | Medium | KEEP |
| | ListFunctions | security | Yes | No | List | Yes | Low | KEEP |
| | ListTags | security | Yes | No | List | Yes | Medium (tag values) | KEEP |
| **logs** | DescribeLogGroups | security | Yes | No | List | Yes | Low | KEEP |
| | DescribeMetricFilters | security | Yes | No | List | Yes | Low | KEEP |
| **organizations** | DescribeOrganization | security | Yes | No | Read | Yes | Low | KEEP |
| | ListAccounts | security | Yes | No | List | Yes | Medium (account names) | KEEP |
| **rds** | DescribeDBClusters | dr | Yes | No | List | Yes | Low | KEEP |
| | DescribeDBEngineVersions | dr | Yes | No | List | Yes | Low | KEEP |
| | DescribeDBInstances | dr | Yes | No | List | Yes | Medium | KEEP |
| | DescribeDBSnapshotAttributes | security | Yes | No | List | Yes | Medium (sharing) | KEEP |
| | DescribeDBSnapshots | security | Yes | No | List | Yes | Low | KEEP |
| | DescribeDBSubnetGroups | dr | Yes | No | List | Yes | Low | KEEP |
| | ListTagsForResource | dr | Yes | No | List | Yes | Medium (tag values) | KEEP |
| **route53** | ListHealthChecks | pulse | Yes | No | List | Yes | Low | KEEP |
| | ListHostedZones | pulse | Yes | No | List | Yes | Medium (zone names) | KEEP |
| | ListResourceRecordSets | pulse | Yes | No | List | Yes | Medium (DNS records) | KEEP |
| **s3** | GetAccountPublicAccessBlock | security | Yes | No | Read | Yes | Low | KEEP |
| | GetBucketAcl | security | Yes | No | Read | Yes | Medium | KEEP |
| | GetBucketLocation | security | Yes | No | Read | Yes | Low | KEEP |
| | GetBucketLogging | security | Yes | No | Read | Yes | Low | KEEP |
| | GetBucketPolicy | security | Yes | No | Read | Yes | High (policy doc) | KEEP |
| | GetBucketPolicyStatus | security | Yes | No | Read | Yes | Low | KEEP |
| | GetBucketPublicAccessBlock | security | Yes | No | Read | Yes | Low | KEEP |
| | GetBucketTagging | security | Yes | No | Read | Yes | Medium (tags) | KEEP |
| | GetBucketVersioning | security | Yes | No | Read | Yes | Low | KEEP |
| | GetEncryptionConfiguration | security | Yes | No | Read | Yes | Low | KEEP |
| | GetLifecycleConfiguration | dr | Yes | No | Read | Yes | Low | KEEP |
| | GetReplicationConfiguration | dr | Yes | No | Read | Yes | Low | KEEP |
| | ListAllMyBuckets | security | Yes | No | List | Yes | Low | KEEP |
| | ListBucket | security | Yes | No | List | Yes | Medium (object names) | KEEP |
| **secretsmanager** | ListSecrets | security | Yes | No | List | Yes | Medium (secret names) | KEEP |
| **servicequotas** | GetServiceQuota | limit | Yes | No | Read | Yes | Low | KEEP |
| | ListRequestedServiceQuotaChangeHistory | limit | Yes | No | List | Yes | Low | KEEP |
| | ListServiceQuotas | limit | Yes | No | List | Yes | Low | KEEP |
| | ListServices | limit | Yes | No | List | Yes | Low | KEEP |
| **sns** | ListTopics | pulse | Yes | No | List | Yes | Low | KEEP |
| **sts** | GetCallerIdentity | core | Yes | No | Read | Yes | Low | KEEP |
| **tag** | GetResources | tag | Yes | No | Read | Yes | Medium (all tagged resources) | KEEP |
| | GetTagKeys | tag | Yes | No | Read | Yes | Low | KEEP |
| | GetTagValues | tag | Yes | No | Read | Yes | Medium (tag values) | KEEP |
| **xray** | GetGroups | pulse | Yes | No | Read | Yes | Low | KEEP |

### Special Analysis: `cloudformation:DetectStackDrift`

AWS classifies this as **Write** access level. Analysis:

- **Does it mutate customer resources?** No. It initiates a drift detection operation on CloudFormation's side.
- **Does it start an AWS-side job?** Yes. It creates a drift detection task that runs asynchronously. The task compares current resource state against the template.
- **Does it create persistent state?** The drift detection results persist in CloudFormation and are queryable via `DescribeStackDriftDetectionStatus`. However, these results are metadata about existing stack state, not new customer resources.
- **Does it cost money?** No direct charge. The detection reads resource state using internal AWS mechanisms.
- **Is "read-only" technically defensible?** Strictly, no. The API creates a transient detection job. However, "no resource mutations" IS defensible. The operation observes the customer's infrastructure without changing it.

**Recommendation:** KEEP. The precise trust wording Kulshan should use requires reviewing ALL actions labeled "Write" or that create AWS-side analytical jobs. The complete set in this policy:

- `cloudformation:DetectStackDrift` - initiates observation job, zero resource mutations
- `iam:GenerateCredentialReport` - creates ephemeral AWS-side credential report
- `iam:GenerateServiceLastAccessedDetails` - creates ephemeral access report

None of these mutate customer resources. None create customer-visible persistent state (beyond ephemeral report artifacts that expire). None bill the customer.

**Recommended trust wording:** "No customer resource mutations. No data writes. No billing changes. Kulshan initiates read-style observation operations only."

This is more precise than "read-only" (which is technically inaccurate given AWS access-level classifications) and more defensible than "zero writes" (which DetectStackDrift technically violates in AWS's IAM taxonomy). Do NOT update live website wording in this release. Record the precise technical contract here; public wording update is a separate editorial decision.

### Special Analysis: `iam:GenerateCredentialReport` and `iam:GenerateServiceLastAccessedDetails`

Both are labeled "Read" by AWS but "generate" suggests creation. Analysis:
- They create ephemeral AWS-side reports (credential report, service access report).
- They do not create customer-visible resources or persistent state beyond the generated report (which expires).
- Standard practice for IAM security auditing.

**Recommendation:** KEEP. Non-controversial.

### Registry entries NOT in composed policy (optional actions)

The registry contains additional actions with `"status": "optional"` and `"baseline_eligible": false`:
- `budgets:DescribeBudgets`, `budgets:DescribeNotificationsForBudget`, `budgets:DescribeSubscribersForNotification`
- `ce:GetAnomalyMonitors`, `ce:GetAnomalySubscriptions`
- `cloudtrail:LookupEvents`
- `kms:Decrypt` (for SSE-KMS CUR buckets)

These are not in the published policy. They are documented in the registry for future use. No action needed.



---

## 21. Privacy Terminology/Claims

### Terms we use

| Term | Meaning | When appropriate |
|---|---|---|
| Pseudonymized | Customer-identifying values replaced with deterministic HMAC-derived aliases. Reversible only with the workspace secret. | Output files, MCP responses, structured stdout |
| Identifiers hidden | General user-facing language for the default behavior. | CLI help text, warnings |
| Real identifiers | Original AWS values shown without transformation. | TTY terminal, `--show-identifiers` |

### Terms we do NOT use

| Avoided term | Why |
|---|---|
| "PII-free" | We transform known identifier classes. Free text fields may contain customer data we do not detect. |
| "Anonymous" | Pseudonymization is reversible with the secret. It is not anonymization. |
| "Safe" / "Sanitized" | Vague. Does not communicate what was transformed. |
| "Redacted" | Legacy term from `redact.py`. Implies information destruction rather than deterministic replacement. |
| "Clean" | Implies absence of all sensitive data, which we cannot guarantee for free text. |

### Output metadata

Every pseudonymized output includes a metadata field:

```json
{
  "pseudonymization": {
    "policy": "normal-v1",
    "engine_version": "0.5.1",
    "note": "Customer-identifying values replaced with deterministic aliases. Service names, regions, costs, and dates are preserved."
  }
}
```

This replaces the current `"redacted": true` boolean.

---

## 22. Performance Constraints

### Requirements

The pseudonymization engine must support:

| Operation | Constraint | Rationale |
|---|---|---|
| Single value HMAC | < 1ms per call | Report findings typically have < 1000 identifiers |
| Payload deep-walk | < 100ms for a 10,000-finding report | Largest realistic report |
| Future DuckDB UDF | Scalar function, no Python state between rows | CUR exports may have millions of rows |
| Future batch mode | Process identifiers without loading all rows | Multi-GB CUR files |
| Memory | No reverse map, no counter state, no growing data structures | HMAC is stateless |

### Design properties that satisfy these

1. **Stateless HMAC**: Each pseudonymization call is `HMAC(secret, canonical_form)`. No lookup table. No counter. No growing state. O(1) per identifier.
2. **No discovery ordering**: Unlike sequential assignment (`acct_01, acct_02`), HMAC does not require tracking which identifiers have been seen.
3. **No reverse map**: The engine does not maintain a mapping from alias back to original. Reversal is a separate future operation that recomputes HMAC against known originals.
4. **Classifier is pattern-based**: Field classification uses compiled regex + field-name sets. No network calls, no file I/O during classification.
5. **DuckDB UDF compatibility**: The HMAC function can be registered as a scalar UDF (`con.create_function("pseudo_account", ...)`) because it requires only the secret (loaded once) and the input value. No cross-row state.

### What would break future performance

- ~~Sequential counters requiring global state~~ (rejected)
- ~~Translation table lookups per row~~ (rejected)
- ~~Loading full CUR into pandas before transformation~~ (rejected)
- ~~Network calls during pseudonymization~~ (rejected)

---

## 23. Backward Compatibility

### Changes visible to users in 0.5.1

| Surface | Change | Breaking? | Migration |
|---|---|---|---|
| JSON file output | Field values pseudonymized by default (previously some were masked, others raw) | Yes, for parsers expecting raw values | `--show-identifiers` restores raw behavior |
| CSV file output | Previously raw; now pseudonymized | Yes (security fix) | `--show-identifiers` |
| JSON stdout (no -o) | Previously raw; now pseudonymized when non-TTY | Yes | `--show-identifiers` |
| HTML report | Masking style changes from `XXXX-XXXX-9012` to `acct_7f31c2a9102d774b` | Yes (visual change) | `--show-identifiers` |
| SARIF report | Same | Yes | `--show-identifiers` |
| Terminal output | No change (real identifiers in TTY, same as before) | No | N/A |
| `--show-pii` flag | Deprecated, hidden alias for `--show-identifiers` | No (still works) | Warning message |
| JSON schema | New `"pseudonymization"` key added; `"redacted": true` retained for backward compat | Additive (non-breaking) | Consumers can check either key |
| History database | `full_result_json` column now pseudonymized | No external impact | Internal change |
| MCP responses | Previously raw; now pseudonymized | Yes for MCP clients parsing account IDs | Clients must use workspace-local tools for real values |
| Reckoner output | Previously raw; now pseudonymized in file/structured output | Yes | `--show-identifiers` |

### Non-breaking changes

- New `--show-identifiers` flag (additive).
- New `pseudonym.key` file in workspace directory (new file, no existing file modified).
- New IAM validation tests (additive).
- `redact.py` still exists (no import breakage during migration).

### Recommended user communication

CHANGELOG entry:

```
## 0.5.1 - Privacy Foundation

**Breaking:** Structured output (JSON, CSV, HTML, SARIF, Reckoner, MCP) now
pseudonymizes customer-identifying values by default. Terminal output is
unchanged. Use `--show-identifiers` to restore raw values in file exports.

**Deprecated:** `--show-pii` is now a hidden alias for `--show-identifiers`.

**Security fix:** CSV exports previously did not apply any privacy transformation.
```

---

## 24. Complete Test Matrix

| ID | Surface | Scenario | Expected behavior | Security invariant | Level |
|---|---|---|---|---|---|
| T01 | HMAC | Same input + same secret | Same output | Determinism | Unit |
| T02 | HMAC | Same input + different secret | Different output | Workspace isolation | Unit |
| T03 | HMAC | Different inputs + same secret | Different outputs | No collisions (probabilistic) | Unit |
| T04 | Canonicalization | ARN containing instance ID vs bare instance ID | Same alias for the resource portion | Consistency | Unit |
| T05 | Canonicalization | Two ARNs with same resource ID but different accounts | Same resource alias, different account alias | Context preservation | Unit |
| T06 | Canonicalization | Email case variants (`A@B.com` vs `a@b.com`) | Same alias | Case normalization | Unit |
| T07 | Canonicalization | IP address in different contexts | Same alias | Consistency | Unit |
| T08 | Secret | Fresh workspace, no secret file | Secret created atomically | Atomic creation | Integration |
| T09 | Secret | Two concurrent processes, no secret | One wins, other reads winner's file | Race safety | Integration |
| T10 | Secret | Corrupt secret file (< 32 bytes) | Regenerated with warning | Corruption recovery | Unit |
| T11 | Secret | Secret file missing permissions (Windows) | Graceful handling | Platform compatibility | Integration |
| T12 | CSV | Report with `show_pii=False` | No raw 12-digit account IDs in output | CSV gap fix | Unit |
| T13 | JSON file | Report output to file | Pseudonymized identifiers, correct format | File output | Integration |
| T14 | JSON stdout | Piped (non-TTY) `--format json` | Pseudonymized | Structured stdout | Integration |
| T15 | JSON stdout | TTY + `--format json` | Pseudonymized (explicit format overrides TTY) | Format semantics | Integration |
| T16 | Terminal | TTY terminal report | Real identifiers shown | TTY bypass | Integration |
| T17 | HTML | Report to HTML file | `acct_7f31c2a9102d774b` format, no raw IDs | HTML output | Integration |
| T18 | SARIF | Report to SARIF file | Pseudonymized in all locations | SARIF output | Integration |
| T19 | Reckoner | JSON output with account grouping | Account values pseudonymized; service values passthrough | Reckoner privacy | Integration |
| T20 | Reckoner | Terminal output (TTY) | Real values shown | TTY bypass | Integration |
| T21 | Reckoner | CSV output | Pseudonymized | Reckoner CSV | Integration |
| T22 | Analyze | JSON brief output | DeltaRow.name (account), OwnerCandidate pseudonymized | Analyze privacy | Integration |
| T23 | Analyze | Markdown output | Same as JSON | Consistency | Integration |
| T24 | MCP | `kulshan_preflight` response | Account and ARN pseudonymized | MCP privacy | Unit |
| T25 | MCP | `kulshan_report` compact findings | Resource ARNs, titles pseudonymized | MCP privacy | Unit |
| T26 | History | `full_result_json` stored in SQLite | Pseudonymized before write | Persistence privacy | Integration |
| T27 | History | `scans.account_id` in SQLite | Raw (needed for lookup) | Functional requirement | Unit |
| T28 | Exceptions | `StsVerificationError` message | No raw account ID in `str(error)` | Exception safety | Unit |
| T29 | Exceptions | `WorkspaceCredentialMismatchError` message | No raw account ID in `str(error)` | Exception safety | Unit |
| T30 | Logs | `payer_binding` INFO log | No raw payer_account_id | Log safety | Unit |
| T31 | Logs | `onboarding` INFO log | No raw account_id | Log safety | Unit |
| T32 | Emails | Email in finding title | Pseudonymized to `user_xxx@pseudo.invalid` | Email handling | Unit |
| T33 | Account IDs | 12-digit in finding evidence dict | Pseudonymized | Pattern scanning | Unit |
| T34 | ARNs | Full ARN in resource_arn field | Composite pseudonym with account+resource replaced | ARN handling | Unit |
| T35 | Resource IDs | `i-0abc123` in resource_id | `res_` prefixed alias | Resource handling | Unit |
| T36 | Access keys | `AKIA...` in finding text | Pseudonymized | Critical data | Unit |
| T37 | IPs | IPv4 in finding | Pseudonymized to `ip_` alias | IP handling | Unit |
| T38 | Hostnames | RDS endpoint in finding | `host_` alias | Hostname handling | Unit |
| T39 | Buckets | S3 bucket name | `bucket_` alias | Bucket handling | Unit |
| T40 | Tags | Tag value in analyze output | `tag_` alias | Tag pseudonymization | Unit |
| T41 | Free text | Finding title with embedded account ID + email | Both pseudonymized | Multi-pattern scanning | Unit |
| T42 | Passthrough | Service name "AmazonEC2" in finding | NOT pseudonymized | Allowlist correctness | Unit |
| T43 | Passthrough | Region "us-east-1" | NOT pseudonymized | Allowlist correctness | Unit |
| T44 | Passthrough | Cost value "$1,234.56" | NOT pseudonymized | Financial preservation | Unit |
| T45 | `--show-identifiers` | Flag passed | All output contains real values | Bypass works | Integration |
| T46 | `--show-pii` | Deprecated flag used | Works + warning on stderr | Backward compat | Integration |
| T47 | Consistency | Same account in JSON and HTML output | Same alias in both | Cross-format consistency | Integration |
| T48 | IAM Gate A | Valid action (e.g., `ec2:DescribeInstances`) | VALID | Gate A correctness | Unit |
| T49 | IAM Gate A | Invalid action (e.g., `s3:GetBucketEncryption`) | INVALID_ACTION, test fails | Gate A detection | Unit |
| T50 | IAM Gate A | Unknown prefix (e.g., `newservice:GetStuff`) | UNVALIDATABLE_PREFIX, warning | Gate A graceful handling | Unit |
| T51 | IAM Gate A | Stale snapshot (> 90 days) | Warning emitted | Staleness detection | Unit |
| T52 | IAM Gate A | Malformed snapshot JSON | Test handles gracefully | Corruption handling | Unit |
| T53 | IAM Gate B | Action in registry + in policy | Pass | Consistency | Unit |
| T54 | IAM Gate B | Action in policy but NOT in registry | Detected, reported | Reverse coverage | Unit |
| T55 | IAM Gate B | Action in registry (required) but NOT in policy | FAIL | Missing permission | Unit |
| T56 | IAM Gate B | Duplicate action in policy | Detected | Policy hygiene | Unit |
| T57 | Secret not in output | Any pseudonymized JSON output | Secret bytes not present as substring | Secret protection | Integration |
| T58 | Secret not in logs | DEBUG-level log capture during report | Secret bytes not present | Secret protection | Integration |
| T59 | No ordering dep | Two runs with different row ordering | Same aliases | HMAC statelessness | Integration |
| T60 | Backward compat | `--show-pii` produces identical output to `--show-identifiers` | Functional equivalence | Migration safety | Integration |

---

## 25. Concrete File-by-File Implementation Plan

### New files

| File | Purpose | Public API | Callers | Dependencies | Security invariant | Tests |
|---|---|---|---|---|---|---|
| `src/kulshan/pseudonym/__init__.py` | Package init, exports | `PseudonymizationEngine`, `create_pseudonym_context` | cli.py, reckoner/cli.py, analyze/export.py, mcp_server/worker.py, history/__init__.py | None | N/A | N/A |
| `src/kulshan/pseudonym/types.py` | `SensitiveId` type, `IdentifierClass` enum | `SensitiveId`, `IdentifierClass` | session.py, workspace/sts.py, workspace/errors.py | None | `__str__` never returns raw | T28, T29 |
| `src/kulshan/pseudonym/secret.py` | Workspace secret generation/loading | `load_or_create_secret(workspace_path) -> bytes` | Engine init | os, pathlib | Atomic creation, 0o600, never exported | T08, T09, T10, T11 |
| `src/kulshan/pseudonym/canonical.py` | Canonicalization logic | `canonicalize(value, id_class) -> str` | Engine | re | Same identity = same canonical form | T04, T05, T06, T07 |
| `src/kulshan/pseudonym/hmac_scheme.py` | HMAC derivation + formatting | `derive_alias(secret, canonical, prefix) -> str` | Engine | hmac, hashlib | Deterministic, one-way | T01, T02, T03 |
| `src/kulshan/pseudonym/engine.py` | `PseudonymizationEngine` class | `pseudonymize_value`, `pseudonymize_payload`, `pseudonymize_text` | All output paths | canonical, hmac_scheme, classifier | No raw identifiers in output when active | T12-T47 |
| `src/kulshan/pseudonym/policy.py` | `PseudonymPolicy` dataclass | `PseudonymPolicy` | Engine init | None | Controls TTY bypass | T16, T20 |
| `src/kulshan/pseudonym/classifier.py` | Field/value classification + column classification API | `FieldClassifier`, `classify_column()`, `ColumnClassification` enum | Engine, future CUR exporter | re | Known identifier classes classified correctly | T42, T43, T44 |
| `iam/aws-service-reference/snapshot-metadata.json` | Vendored snapshot metadata | N/A | Gate A test | N/A | Timestamp, hash | T51 |
| `iam/aws-service-reference/services/*.json` | Per-service action catalogs | N/A | Gate A test | N/A | Source of truth for action validation | T48, T49, T50 |
| `iam/refresh_service_reference.py` | Snapshot refresh script | CLI: `python iam/refresh_service_reference.py` | Maintainer (manual) | httpx | Fetches from AWS, writes locally | T52 |
| `tests/unit/test_pseudonym_engine.py` | Core engine unit tests | N/A | pytest | engine, fixtures | All T01-T44 | All unit tests |
| `tests/unit/test_iam_gate_a.py` | Gate A validation tests | N/A | pytest | policy, snapshot | T48-T52 | Gate A tests |
| `tests/unit/test_iam_gate_b.py` | Gate B coverage tests | N/A | pytest | registry, policy | T53-T56 | Gate B tests |
| `tests/integration/test_privacy_integration.py` | End-to-end privacy tests | N/A | pytest | Full CLI | T13-T27, T47, T57-T59 | Integration tests |

### Modified files

| File | Change | Reason |
|---|---|---|
| `src/kulshan/cli.py` | Replace `redact_payload()` calls in `_emit_output()` with engine; add `--show-identifiers` flag; add TTY detection; add `pseudonymization` metadata to JSON | Central output dispatch |
| `src/kulshan/reckoner/cli.py` | Insert `engine.pseudonymize_payload()` call before `_render()` dispatch | Reckoner output path |
| `src/kulshan/analyze/export.py` | Insert pseudonymization in `export_brief()` before format dispatch | Analyze output path |
| `src/kulshan/mcp_server/tools.py` | Pseudonymize `_execute_preflight()` response and `_compact_finding()` output | MCP privacy |
| `src/kulshan/mcp_server/worker.py` | Accept workspace path; create engine in worker process | MCP engine context |
| `src/kulshan/history/__init__.py` | Pseudonymize `full_result_json` in `save_scan()` and `save_consolidated_scan()` | History persistence |
| `src/kulshan/session.py` | Wrap `get_account_id()` return in `SensitiveId` | Exception safety |
| `src/kulshan/workspace/sts.py` | Return `SensitiveId` for account_id in verification results | Exception safety |
| `src/kulshan/workspace/errors.py` | Accept `SensitiveId` in `WorkspaceCredentialMismatchError` | Exception safety |
| `src/kulshan/workspace/payer_binding.py` | Mask account IDs in logger.info calls | Log safety |
| `src/kulshan/workspace/onboarding.py` | Mask account IDs in logger.info calls | Log safety |
| `src/kulshan/workspace/federated_history.py` | Mask payer IDs in logger.warning call | Log safety |
| `src/kulshan/report/csv_export.py` | No change (fix is in cli.py caller) | N/A |
| `iam/registry.json` | Add `source_module` field to entries for cost, security, dr capabilities | Gate B |
| `pyproject.toml` | No new dependencies needed (hmac, hashlib, os are stdlib) | N/A |



---

## 26. PR/Commit Sequencing

### Phase 0: Immediate safety fix

| PR | Content | Effort | Risk | Gate |
|---|---|---|---|---|
| **PR 0: CSV redaction gap** | 3-line fix in `cli.py` applying `redact_payload()` to CSV findings. Add `test_csv_export_does_not_contain_raw_account_id`. | S | Low | Test passes; CSV output contains no raw 12-digit IDs. |

**Smallest safe first PR.** Can ship independently before any architecture work.

### Phase 1: Pseudonymization foundation

| PR | Content | Effort | Risk | Gate |
|---|---|---|---|---|
| **PR 1: Types + secret** | `pseudonym/types.py` (SensitiveId, IdentifierClass enum), `pseudonym/secret.py` (load/create), unit tests. | M | Low | T01 atomicity, T08-T11 pass. |
| **PR 2: Canonicalization + HMAC** | `pseudonym/canonical.py`, `pseudonym/hmac_scheme.py`, unit tests. | M | Medium (correctness of canonical rules) | T01-T07 pass. |
| **PR 3: Engine + classifier** | `pseudonym/engine.py`, `pseudonym/policy.py`, `pseudonym/classifier.py`, property-based free text tests. | L | Medium | T33-T44 pass. Engine correctly classifies and transforms identifiers. |

### Phase 2: Output path migration

| PR | Content | Effort | Risk | Gate |
|---|---|---|---|---|
| **PR 4: Report pipeline** | Wire engine into `_emit_output()` for JSON/HTML/SARIF/CSV. Add `--show-identifiers` flag. TTY detection. Update JSON schema (add `pseudonymization` key, remove `redacted`). | L | **High** (most user-visible change) | T12-T18, T45-T47, T57-T60 pass. |
| **PR 5: Reckoner pipeline** | Wire engine into `reckoner/cli.py:_render()`. Pseudonymize account/payer grouping values; passthrough service/region. | M | Medium | T19-T21 pass. |
| **PR 6: Analyze + MCP** | Wire engine into `analyze/export.py:export_brief()` and MCP worker. | M | Medium | T22-T25 pass. |
| **PR 7: History + exceptions + logs** | Pseudonymize `full_result_json`; wrap SensitiveId at entry points; fix 4 logger call sites. | M | Low | T26-T31 pass. |

### Phase 3: IAM gates

| PR | Content | Effort | Risk | Gate |
|---|---|---|---|---|
| **PR 8: Gate A snapshot + validation** | `iam/refresh_service_reference.py`, vendored snapshot, `tests/unit/test_iam_gate_a.py`. | M | Low | T48-T52 pass. All 160 actions validated. |
| **PR 9: Gate B registry extension** | Add `source_module` to registry entries (cost, security, dr). `tests/unit/test_iam_gate_b.py`. | M | Low | T53-T56 pass. |

### Phase 4: CUR classification primitives (foundation for 0.6.0)

| PR | Content | Effort | Risk | Gate |
|---|---|---|---|---|
| **PR 10: Classification API** | `pseudonym/classifier.py` with `ColumnClassification` enum and `classify_column()` function. Small test fixture with ~15 example columns proving the API. No comprehensive CUR registry. | S | Low | API compiles; test fixture classifies correctly. |

### Phase 5: Cleanup + documentation

| PR | Content | Effort | Risk | Gate |
|---|---|---|---|---|
| **PR 11: Delete redact.py** | Remove `redact.py`, `redact_payload()` imports, `_redact_payer()`, `mask_account_id()`. Update remaining references. | M | Medium (import breakage) | All existing tests pass without `redact.py`. |
| **PR 12: Documentation + CHANGELOG + version** | Update README, CHANGELOG, docstrings. Bump `__version__.py` to `0.5.1`. Update `__release_date__`. | S | Low | No raw IDs in any doc example. Version correct. |

### Dependency graph

```
PR 0 (independent, can ship immediately)

PR 1 -> PR 2 -> PR 3 -> PR 4 -> PR 5, PR 6, PR 7 (parallel after PR 4)
                                   |
                                   v
                                 PR 11 -> PR 12

PR 8, PR 9 (independent of privacy engine, can parallel with Phase 2)
PR 10 (depends on PR 3 for classifier module)
```

**Highest-risk PR: PR 4** (report pipeline migration). This is the most user-visible change and touches the central output dispatch. Must have comprehensive integration tests before merge.

---

## 27. Risk Register

| # | Risk | Severity | Likelihood | Mitigation |
|---|---|---|---|---|
| R1 | HMAC collision (two different identifiers produce same alias) | Low | Negligible (64-bit space, collision at ~600M values) | Fixed 16-hex-char token. Practically zero risk for any real workload. If ever detected: fail loudly rather than silently merging identities. |
| R2 | Canonicalization bug: same identity produces different aliases in different contexts | High | Medium | Extensive unit tests (T04-T07). Property-based testing. |
| R3 | Secret file created with wrong permissions on Windows | Low | Medium | Windows does not honor POSIX chmod. Accept inherited ACL from platformdirs user_data_dir. Document. |
| R4 | Existing CI/automation parses raw account IDs from JSON output | High | Medium | `--show-identifiers` escape hatch. CHANGELOG notice. Deprecation period. |
| R5 | MCP clients break when account IDs become aliases | Medium | Low | MCP tools that need real identity can use `kulshan_preflight` with `--show-identifiers` flag (future MCP parameter). |
| R6 | Performance regression on large reports (10,000+ findings) | Low | Low | HMAC is O(1) per value. Deep-walk is O(n) in output size. Benchmark test. |
| R7 | `full_result_json` pseudonymization breaks history delta comparison | Low | Very low | Delta comparison uses `scans.account_id` (kept raw), not full_result_json. |
| R8 | Unknown CUR columns in future consultant export block users | Medium | Medium (AWS adds columns) | `--drop-unclassified-columns` escape in 0.6.0. Clear error message. |
| R9 | Free text scanning misses an embedded identifier | Medium | Medium | Pattern-based scanning is not exhaustive. Documented limitation. "No known direct identifiers detected" not "PII-free". |
| R10 | Service Authorization Reference snapshot becomes stale, new valid actions flagged as invalid | Low | Low | Warning at 90 days. Refresh script. Does not block development. |
| R11 | `cloudformation:DetectStackDrift` creates public perception issue | Medium | Low | Document explicitly. Update wording to "no resource mutations." |
| R12 | SensitiveId adoption causes type errors in existing code | Low | Medium | Scoped to 5 entry points. `SensitiveId` supports `==`, `hash`, `str` comparisons. |

---

## 28. Explicit Non-Goals

The following are NOT in scope for 0.5.1:

| Item | Why | Target release |
|---|---|---|
| Consultant export command (`kulshan export consultant`) | Separate product feature | 0.6.0 |
| CUR full-schema export with DuckDB UDF pseudonymization | Depends on consultant export | 0.6.0 |
| CE evidence export (multi-dimension Parquet) | Depends on consultant export | 0.6.0 |
| ZIP packaging with manifest and privacy report | Consultant export deliverable | 0.6.0 |
| Three-gate privacy validation (schema/integrity/residual) | Consultant export quality gate | 0.6.0 |
| `--keep-tag` CLI flag | Consultant export feature | 0.6.0 |
| `--drop-unclassified-columns` flag | Consultant export feature | 0.6.0 |
| `kulshan pseudonym reveal` command | Post-foundation feature | 0.6.0+ |
| Customer-side label file (`pseudonym-labels.toml`) | Convenience feature, not security-critical | 0.6.0+ |
| `kulshan pseudonym reveal` command | HMAC is intentionally one-way; reveal needs enumeration/mapping semantics | 0.6.0+ (if validated as useful) |
| OptScale-inspired cost optimization checks | Separate workstream | 0.7.0 |
| Instance generation detection | Separate workstream | 0.7.0 |
| Multi-machine workspace secret synchronization | Complex distributed state | Not planned |
| Reckoner directory/class rename | Explicitly ruled out (name stays) | Never |
| Multi-cloud support | Out of product scope | Never |
| Vocabulary allowlist for service names/usage types (giant string list) | Field classification makes it unnecessary for 0.5.1 | Evaluate in 0.6.0 |
| Full SensitiveId wrapping of all str fields in all dataclasses | Excessive refactoring for marginal gain | Evaluate in 0.7.0 |

---

## 29. Acceptance Criteria for 0.5.1

The release is complete when:

1. All 60 tests in the test matrix (section 24) pass.
2. CSV export no longer contains raw account IDs (security fix confirmed).
3. JSON file output contains pseudonymized identifiers by default.
4. HTML, SARIF file output contains pseudonymized identifiers.
5. Reckoner JSON/CSV/Markdown output contains pseudonymized identifiers.
6. Analyze JSON/Markdown output contains pseudonymized identifiers.
7. MCP tool responses contain pseudonymized identifiers.
8. `full_result_json` in history SQLite is pseudonymized before storage.
9. Terminal TTY output still shows real identifiers (no regression for interactive use).
10. `--show-identifiers` flag works across all output paths.
11. `--show-pii` works as deprecated alias with warning.
12. IAM Gate A: all 160 policy actions validated against vendored snapshot; zero INVALID_ACTION.
13. IAM Gate B: all required+baseline_eligible registry actions confirmed present in composed policy.
14. `pseudonym.key` created atomically with restricted permissions.
15. No raw workspace secret bytes appear in any output, log, or exception message.
16. CHANGELOG documents breaking changes.
17. `redact.py` is deleted (no longer importable).
18. No new dependencies added to `pyproject.toml` (hmac, hashlib, os are stdlib).
19. All existing tests pass (with updates for new output format).
20. Column classification API (`ColumnClassification` enum + `classify_column()`) exists and is proven by test fixture.
21. Alias token is ALWAYS exactly 16 lowercase hexadecimal characters.
22. Corrupt workspace secret fails closed with clear user instructions (no silent regeneration).

---

## 30. What 0.6.0 Consultant Export Reuses

| 0.5.1 component | 0.6.0 usage |
|---|---|
| `PseudonymizationEngine` | Called with `consultant` policy mode (no TTY bypass, no `--show-identifiers`) |
| `pseudonym/canonical.py` | Same canonicalization for CUR column values |
| `pseudonym/hmac_scheme.py` | Same HMAC derivation for DuckDB UDF registration |
| `pseudonym/classifier.py` | `ColumnClassification` enum extended with comprehensive `cur_columns.toml` registry |
| `pseudonym/cur_columns.toml` | Comprehensive registry built in 0.6.0 using the classification API from 0.5.1 |
| `ColumnClassification` enum | PASSTHROUGH/PSEUDONYMIZE/TRANSFORM_TAG/DROP/UNCLASSIFIED categories |
| `pseudonym/secret.py` | Same workspace secret for consultant export (ensures CUR and CE aliases match) |
| `IdentifierClass` enum | Same identifier taxonomy for CUR column -> identifier class mapping |
| `PseudonymPolicy` | Extended with `consultant` mode (no bypass, block on unknown columns) |
| `FieldClassifier` | Extended with CUR-specific column patterns |
| IAM Gate A infrastructure | Validates any new actions added for consultant export features |
| IAM Gate B mechanism | Declares REQUIRED_ACTIONS for new CE/CUR-access modules |

### What 0.6.0 must add (not in 0.5.1)

- Comprehensive `cur_columns.toml` registry for all CUR 2.0 columns
- `EvidenceScope` dataclass (date/service/account filtering)
- DuckDB UDF registration wrapping `derive_alias()`
- CUR exporter with `COPY ... TO` Parquet
- CE multi-dimension fetcher
- Three-gate validation (schema + integrity + residual scan)
- ZIP packager with manifest
- `kulshan export consultant` CLI command
- `--keep-tag` flag
- `--drop-unclassified-columns` flag
- Interactive mode with prompt_toolkit
- `kulshan pseudonym reveal` (if validated as useful)

---

## 31. Deferred but Important

| Item | Severity | Why deferred | Recommended release |
|---|---|---|---|
| Property-based fuzz testing for free text scanning | Medium | Requires `hypothesis` dependency addition | 0.5.2 or 0.6.0 |
| `s3:ListBucket` metadata sensitivity review | Low | Returns object keys which could contain PII in names | 0.6.0 (relevant when CUR S3 access is used in consultant export) |
| `real-cur/` directory in repo root (may contain production data) | High | Not part of privacy engine work; needs manual review | Immediate (separate from release) |
| Sample HTML reports in repo root (may contain real account IDs) | Medium | Need regeneration or deletion | 0.5.1 cleanup PR or immediately |
| Reckoner cache directory (`reckoner/cache/`) future behavior | Low | Directory exists but no implementation at HEAD | When Reckoner cache is implemented |
| Cross-machine pseudonym stability for teams | Low | Requires shared secret mechanism | Not planned; use `reveal` command |
| Workspace backup/sync guidance documentation | Low | Users who back up workspace to cloud sync may expose secret | 0.6.0 documentation |

---

## 32. What Could Make This Architecture Wrong?

### Privacy bypasses

1. **Free text fields we do not scan**: Finding `evidence` dicts contain arbitrary AWS API response fragments. Our pattern scanning catches 12-digit numbers, ARNs, emails, IPs, access keys. It does NOT catch: custom resource names that happen to contain customer information (e.g., S3 object keys like `customer-data/john-smith/`), or AWS-generated identifiers we have not enumerated (e.g., future new resource ID prefixes).

   **Mitigation**: We use "no known direct identifiers detected" language, not "PII-free". The architecture is extensible (add patterns to classifier). Future consultant export adds the residual scan gate.

2. **Tag values that look like AWS vocabulary**: A tag value `us-east-1` would be pseudonymized even though it matches a region code. This is correct (conservative) behavior. But a tag value `production` is also pseudonymized, which reduces utility. This is the intended tradeoff.

3. **Terminal screenshots**: Real identifiers in TTY output can be captured via screenshot. Mitigated by: this is the user's own terminal showing their own data.

### Alias inconsistency

4. **Canonicalization error**: If `canonical.py` produces different canonical forms for the same identity in different code paths, the same resource gets two different aliases. This would confuse analysts comparing CUR and CE data.

   **Mitigation**: Comprehensive canonicalization tests (T04-T07). The canonical rules are centralized in one module, not duplicated.

5. **HMAC truncation collision**: With 16 hex chars (64 bits), collision probability is negligible for practical workloads (birthday bound at ~4 billion values). This is effectively a non-issue. If a collision were ever detected: the system should fail loudly rather than silently merging two identities under one alias.

### Secret leakage

6. **Secret in error messages**: If code accidentally formats the secret bytes into a string (e.g., logging the engine object), the secret could leak.

   **Mitigation**: The engine's `__repr__` and `__str__` never expose the secret. The secret is stored as a private attribute (`_secret`). Tests assert secret bytes never appear in output (T57, T58).

### Identifier classes we missed

7. **AWS Organizations OU IDs** (`ou-xxxx-xxxxxxxx`): Not currently surfaced in Kulshan output but could appear in future organization-aware checks.

8. **AWS SSO permission set names**: Could appear in IAM findings. Currently opaque strings that would be caught by free text scanning if they match identifier patterns.

9. **CloudWatch log group names**: Can contain customer-chosen identifiers. Currently surfaced in findings but not classified as a separate identifier class. Caught by free text pattern scanning.

### False privacy claims

10. **Cost amounts ARE confidential**: Even with all identifiers pseudonymized, the cost structure of an organization is sensitive business information. Our privacy engine does not address data confidentiality of financial values, only identifier pseudonymization. The documentation must be clear about this distinction.

### Performance traps

11. **Deep-walk on very large payloads**: If a report produces a `full_result_json` of 50MB (extreme case with 10,000+ findings and full evidence dicts), the deep-walk pseudonymization could be slow. Mitigated by: this is writing to local SQLite, not interactive. A 50MB JSON walk at Python speed takes seconds, not minutes.

12. **Future DuckDB UDF call overhead**: Python UDFs in DuckDB have per-row function call overhead. For a 20M row CUR, this could be significant. Mitigated by: DuckDB supports vectorized UDFs. The HMAC computation itself is fast (~1us per call). At 20M rows, that is ~20 seconds total HMAC time, acceptable for an export operation.

### Windows/Linux differences

13. **File permissions**: `os.chmod(path, 0o600)` is a no-op on Windows (NTFS uses ACLs). The secret file on Windows inherits the parent directory's ACL, which platformdirs sets to user-specific. This is acceptable but not as strong as POSIX 0o600.

14. **Atomic file creation**: `O_CREAT | O_EXCL` works on both platforms. No Windows-specific concern.

---

## 33. Final Recommendation

**GO.**

All corrections applied:
- Alias length: 16 hex characters (64 bits). Zero surviving 6-char references.
- Canonicalization: identifier-class-aware, no generic ARN stripping. Tests prove both equivalence AND non-collapse.
- CUR classification: API primitives only in 0.5.1. Comprehensive registry deferred to 0.6.0.
- Corrupt secret: fail-closed, user must deliberately delete to reset.
- Reveal command: removed from 0.5.1 scope entirely.
- Trust wording: precise analysis provided. No automatic website update.
- `real-cur/` security check: CLEAR (gitignored, never committed).
- Vocabulary: no giant vendored allowlist. Structural field classification preferred.
- Backward compat: `"redacted": true` retained alongside new `"pseudonymization"` key.

The architecture is coherent, the scope is bounded, the risks are manageable, and the foundation directly enables 0.6.0 consultant export without requiring a second privacy system.
