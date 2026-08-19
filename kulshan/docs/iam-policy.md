# IAM Policy

## Source Files

| File | Description |
|------|-------------|
| `kulshan/iam/kulshan-readonly.json` | Composed union of all pack policies (source of truth) |
| `kulshan/iam/per-check/<key>.json` | Per-pack policies (10 files, one per pack) |

The composed policy is the exact union of all per-check policies: 160 unique IAM actions across 32 AWS services. It grants no permission to create, modify, or delete customer resources. Every action is classified non-write in the AWS Service Authorization Reference snapshot dated 2026-08-19.

Three actions do not use Get, List, or Describe naming:

- `cloudformation:DetectStackDrift`
- `iam:GenerateCredentialReport`
- `iam:GenerateServiceLastAccessedDetails`

All three are classified non-write by AWS in that snapshot.

## Website

The policy is published at [missionfinops.com/policy/](https://missionfinops.com/policy/) with:
- A SHA256 hash for verification
- A downloadable JSON link

To verify integrity:

```bash
sha256sum kulshan/iam/kulshan-readonly.json
```

Compare against the hash displayed on the website.

## Licensing

The IAM policy file is licensed under **CC BY 4.0** (separately from the Apache 2.0 codebase). Other tools and compliance teams may reuse it with attribution.

## Adding New IAM Actions

When you add a check that requires additional AWS permissions:

1. Add the actions to `kulshan/iam/per-check/<key>.json` for the relevant pack.
2. Regenerate the composed policy at `kulshan/iam/kulshan-readonly.json`.
3. Update the SHA256 hash on the website (`policy/index.html`).

## Quick Start for Users

Three options depending on how precise you want to be:

| Approach | What to attach |
|----------|---------------|
| Broadest | `ViewOnlyAccess` + `SecurityAudit` + `AWSBillingReadOnlyAccess` managed policies |
| Precise | Use `kulshan/iam/kulshan-readonly.json` directly as a custom policy |
| Scoped | Use individual `per-check/<key>.json` policies for specific packs only |
