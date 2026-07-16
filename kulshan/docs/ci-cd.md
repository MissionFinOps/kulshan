# CI/CD Integration

Kulshan is designed for automated pipeline use. This guide covers GitHub Actions, GitLab CI, and general automation patterns.

---

## Key Flags for Automation

| Flag | Purpose |
|------|---------|
| `--yes` / `-y` | Skip all interactive confirmations |
| `--format json` | Machine-readable output |
| `--format sarif` | GitHub Security tab compatible |
| `-o PATH` | Write to file instead of stdout |
| `--no-history` | Don't persist scan (ephemeral CI runs) |
| `--packs` | Select specific packs |
| `--regions` | Pin regions (avoid auto-detection variability) |

---

## Exit Codes

| Code | Meaning | CI Behavior |
|------|---------|-------------|
| 0 | No critical findings | Pipeline passes |
| 1 | Critical findings detected | Pipeline fails (if configured) |
| 2 | Runtime error | Pipeline fails |
| 3 | Configuration/credential error | Pipeline fails |

Use exit code 1 as a quality gate: fail the pipeline when critical findings are present.

---

## GitHub Actions

### Basic security scan

```yaml
name: Kulshan Security Scan
on:
  push:
    branches: [main]
  pull_request:
    branches: [main]
  schedule:
    - cron: '0 6 * * 1'  # Weekly Monday 6am UTC

permissions:
  id-token: write    # For OIDC authentication
  contents: read
  security-events: write  # For SARIF upload

jobs:
  kulshan:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - uses: actions/setup-python@v5
        with:
          python-version: '3.12'

      - name: Install Kulshan
        run: pip install kulshan

      - name: Configure AWS credentials
        uses: aws-actions/configure-aws-credentials@v4
        with:
          role-to-assume: arn:aws:iam::123456789012:role/KulshanAudit
          aws-region: us-east-1

      - name: Run security scan
        run: |
          kulshan report \
            --packs security,sweep \
            --regions us-east-1 \
            --format sarif \
            -o results.sarif \
            --yes \
            --no-history

      - name: Upload SARIF
        if: always()
        uses: github/codeql-action/upload-sarif@v3
        with:
          sarif_file: results.sarif
          category: kulshan
```

### Cost baseline with artifact

```yaml
name: Kulshan Cost Baseline
on:
  schedule:
    - cron: '0 8 1 * *'  # Monthly, 1st at 8am UTC

jobs:
  cost-baseline:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/setup-python@v5
        with:
          python-version: '3.12'

      - name: Install Kulshan
        run: pip install kulshan

      - name: Configure AWS credentials
        uses: aws-actions/configure-aws-credentials@v4
        with:
          role-to-assume: ${{ secrets.KULSHAN_ROLE_ARN }}
          aws-region: us-east-1

      - name: Run cost baseline
        run: |
          kulshan report \
            --packs cost \
            --days 90 \
            --format json \
            -o cost-baseline.json \
            --yes \
            --no-history

      - name: Generate HTML report
        run: |
          kulshan convert \
            -i cost-baseline.json \
            --format html \
            -o cost-report.html

      - name: Upload artifacts
        uses: actions/upload-artifact@v4
        with:
          name: kulshan-cost-report
          path: |
            cost-baseline.json
            cost-report.html
          retention-days: 90
```

### Full audit with quality gate

```yaml
name: Kulshan Full Audit
on:
  workflow_dispatch:

jobs:
  audit:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/setup-python@v5
        with:
          python-version: '3.12'

      - run: pip install kulshan

      - uses: aws-actions/configure-aws-credentials@v4
        with:
          role-to-assume: ${{ secrets.KULSHAN_ROLE_ARN }}
          aws-region: us-east-1

      - name: Run full audit
        id: audit
        run: |
          kulshan report \
            --packs all \
            --regions us-east-1 \
            --format json \
            -o audit.json \
            --yes \
            --no-history
        continue-on-error: true

      - name: Check for critical findings
        run: |
          SCORE=$(jq '.overall_score' audit.json)
          CRITICALS=$(jq '[.findings[] | select(.severity == "critical")] | length' audit.json)
          echo "Score: $SCORE"
          echo "Critical findings: $CRITICALS"
          if [ "$CRITICALS" -gt 0 ]; then
            echo "::error::$CRITICALS critical findings detected (score: $SCORE)"
            exit 1
          fi
```

---

## GitLab CI

### Security scan

```yaml
kulshan-security:
  image: python:3.12-slim
  stage: test
  before_script:
    - pip install kulshan
  script:
    - kulshan report
        --packs security,sweep
        --regions us-east-1
        --format json
        -o gl-kulshan-report.json
        --yes
        --no-history
  artifacts:
    paths:
      - gl-kulshan-report.json
    reports:
      # GitLab doesn't natively support SARIF, but you can use JSON artifacts
      dotenv: kulshan-score.env
  rules:
    - if: $CI_PIPELINE_SOURCE == "schedule"
    - if: $CI_PIPELINE_SOURCE == "merge_request_event"
```

### Scheduled cost report

```yaml
kulshan-cost:
  image: python:3.12-slim
  stage: audit
  before_script:
    - pip install kulshan
  script:
    - kulshan report --packs cost --days 90 --format json -o cost.json --yes --no-history
    - kulshan convert -i cost.json --format html -o cost-report.html
  artifacts:
    paths:
      - cost.json
      - cost-report.html
    expire_in: 90 days
  rules:
    - if: $CI_PIPELINE_SOURCE == "schedule"
```

---

## AWS Authentication in CI

### GitHub Actions with OIDC (recommended)

No long-lived secrets. Uses GitHub's OIDC provider to assume an IAM role:

```yaml
- uses: aws-actions/configure-aws-credentials@v4
  with:
    role-to-assume: arn:aws:iam::123456789012:role/KulshanCI
    aws-region: us-east-1
```

Trust policy for the role:

```json
{
  "Version": "2012-10-17",
  "Statement": [{
    "Effect": "Allow",
    "Principal": {
      "Federated": "arn:aws:iam::123456789012:oidc-provider/token.actions.githubusercontent.com"
    },
    "Action": "sts:AssumeRoleWithWebIdentity",
    "Condition": {
      "StringEquals": {
        "token.actions.githubusercontent.com:aud": "sts.amazonaws.com"
      },
      "StringLike": {
        "token.actions.githubusercontent.com:sub": "repo:your-org/your-repo:*"
      }
    }
  }]
}
```

### GitLab CI with OIDC

```yaml
variables:
  AWS_ROLE_ARN: arn:aws:iam::123456789012:role/KulshanCI

before_script:
  - >
    STS=$(aws sts assume-role-with-web-identity
    --role-arn $AWS_ROLE_ARN
    --role-session-name gitlab-ci
    --web-identity-token $CI_JOB_JWT_V2)
  - export AWS_ACCESS_KEY_ID=$(echo $STS | jq -r '.Credentials.AccessKeyId')
  - export AWS_SECRET_ACCESS_KEY=$(echo $STS | jq -r '.Credentials.SecretAccessKey')
  - export AWS_SESSION_TOKEN=$(echo $STS | jq -r '.Credentials.SessionToken')
```

### Static credentials (not recommended)

Store in CI secrets only if OIDC is not available:

```yaml
env:
  AWS_ACCESS_KEY_ID: ${{ secrets.AWS_ACCESS_KEY_ID }}
  AWS_SECRET_ACCESS_KEY: ${{ secrets.AWS_SECRET_ACCESS_KEY }}
```

---

## Multi-Account Scanning

Scan multiple AWS accounts in a matrix:

```yaml
jobs:
  audit:
    strategy:
      matrix:
        account:
          - { name: prod, role: "arn:aws:iam::111111111111:role/KulshanAudit" }
          - { name: staging, role: "arn:aws:iam::222222222222:role/KulshanAudit" }
          - { name: dev, role: "arn:aws:iam::333333333333:role/KulshanAudit" }
    steps:
      - uses: aws-actions/configure-aws-credentials@v4
        with:
          role-to-assume: ${{ matrix.account.role }}
          aws-region: us-east-1

      - run: |
          kulshan report \
            --packs security,sweep \
            --regions us-east-1 \
            --format json \
            -o ${{ matrix.account.name }}-scan.json \
            --yes --no-history
```

---

## Parsing Results

### Extract score

```bash
SCORE=$(kulshan report --format json --yes | jq '.overall_score')
```

### Count findings by severity

```bash
kulshan report --format json --yes -o scan.json
CRITICAL=$(jq '[.findings[] | select(.severity == "critical")] | length' scan.json)
HIGH=$(jq '[.findings[] | select(.severity == "high")] | length' scan.json)
```

### Quality gate logic

```bash
#!/bin/bash
kulshan report --packs security --format json -o scan.json --yes --no-history

SCORE=$(jq '.overall_score' scan.json)
CRITICALS=$(jq '[.findings[] | select(.severity == "critical")] | length' scan.json)

if [ "$CRITICALS" -gt 0 ]; then
  echo "FAIL: $CRITICALS critical findings (score: $SCORE)"
  exit 1
elif [ "$SCORE" -lt 70 ]; then
  echo "WARN: Score $SCORE is below threshold 70"
  exit 0  # Warning, don't fail pipeline
else
  echo "PASS: Score $SCORE, no critical findings"
  exit 0
fi
```

---

## Scheduling Recommendations

| Scan Type | Frequency | Packs | Use Case |
|-----------|-----------|-------|----------|
| Security posture | Daily or on PR | security | Gate deployments |
| Cost baseline | Weekly or monthly | cost | Track spend trends |
| Full audit | Monthly | all | Executive reporting |
| Waste detection | Weekly | sweep | Cleanup sprints |
| DR readiness | Monthly | dr | Compliance evidence |

---

## Performance in CI

- **Cost pack only:** ~30s, ~$0.15
- **Security + sweep:** ~40s, free APIs
- **All 10 packs, 1 region:** ~2–3 minutes
- **All 10 packs, 3 regions:** ~4–5 minutes

Use `--regions` to pin regions and avoid variable runtimes from auto-detection.
