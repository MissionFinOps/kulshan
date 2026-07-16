# Output Formats & Reports

Kulshan produces reports in five formats. All formats contain the same underlying data — they differ only in presentation.

---

## Format Selection

```bash
# Explicit format flag
kulshan report --format json -o scan.json

# Auto-detected from file extension
kulshan report -o report.html        # → HTML
kulshan report -o scan.json          # → JSON
kulshan report -o results.sarif      # → SARIF
kulshan report -o findings.csv       # → CSV
```

## Converting Between Formats

Re-render a previous JSON scan without re-running:

```bash
kulshan convert -i scan.json --format html -o report.html
kulshan convert -i scan.json --format sarif -o results.sarif
kulshan convert -i scan.json --format csv -o findings.csv
```

---

## Terminal

Default output when no `--format` or `-o` is specified.

Features:
- Color-coded severity indicators
- Per-pack score cards with letter grades
- Top findings table ranked by impact
- Overall score with trend indicator (if history available)
- Executive summary paragraph
- Timing and API cost information

---

## HTML

Self-contained HTML report suitable for sharing with stakeholders.

```bash
kulshan report -o report.html
```

Features:
- No external dependencies (CSS/JS inlined)
- Interactive charts (cost trends, severity distribution)
- Expandable finding details
- Print-friendly layout
- Score dashboard with per-pack breakdown
- Executive summary section
- Can be opened in any browser and emailed as-is

Account IDs are redacted by default. Use `--show-pii` to include full IDs.

---

## JSON

Structured machine-readable output for CI/CD pipelines and programmatic consumption.

```bash
kulshan report --format json -o scan.json
```

### Top-level schema

```json
{
  "kulshan_version": "0.3.0",
  "account_id": "XXXX-XXXX-5678",
  "regions": ["us-east-1"],
  "duration_seconds": 32.4,
  "overall_score": 78,
  "overall_grade": "C",
  "scan_metadata": {
    "report_status": "complete",
    "payer_cost_coverage": "verified_payer_wide",
    "connections": [...],
    "total_connections": 2,
    "successful_connections": 2,
    "payer_account_id": "999999999999"
  },
  "tools": {
    "cost": {
      "score": 72,
      "grade": "C",
      "finding_count": 5,
      "duration_seconds": 4.8
    }
  },
  "findings": [...],
  "top_actions": [...]
}
```

### Finding object

See [Audit Packs — Finding Schema](audit-packs.md#finding-schema) for the full v2.0 schema with all fields documented.

### Using JSON output in scripts

```bash
# Count critical findings
kulshan report --format json --yes | jq '[.findings[] | select(.severity == "critical")] | length'

# Extract findings for a specific pack
kulshan report --format json --yes | jq '.findings[] | select(.pack == "security")'

# Get overall score
kulshan report --format json --yes | jq '.overall_score'
```

---

## SARIF

[Static Analysis Results Interchange Format](https://sarifweb.azurewebsites.net/). Compatible with:
- GitHub Security tab (Code Scanning)
- Azure DevOps
- VS Code SARIF Viewer extension
- Any SARIF 2.1.0 consumer

```bash
kulshan report --format sarif -o results.sarif
```

### GitHub Integration

Upload SARIF to GitHub Code Scanning:

```yaml
- name: Upload SARIF
  uses: github/codeql-action/upload-sarif@v3
  with:
    sarif_file: results.sarif
    category: kulshan
```

Findings appear in the Security tab as code scanning alerts, with severity mapping:
- critical → error
- high → error
- medium → warning
- low → note
- info → note

---

## CSV

Spreadsheet-friendly export with one row per finding.

```bash
kulshan report --format csv -o findings.csv
```

### Columns

| Column | Description |
|--------|-------------|
| `id` | Finding ID |
| `pack` | Audit pack name |
| `kind` | Finding type |
| `severity` | critical/high/medium/low/info |
| `title` | Finding title |
| `description` | Detailed description |
| `resource_arn` | Affected resource ARN |
| `region` | AWS region |
| `service` | AWS service name |
| `estimated_monthly_impact` | Dollar impact |
| `confidence` | 0.0–1.0 |
| `effort` | Remediation effort |
| `risk` | Remediation risk |
| `recommended_action` | Suggested next step |

Useful for:
- Importing into JIRA/ServiceNow
- Pivot tables in Excel/Google Sheets
- Custom reporting workflows
- Tracking remediation progress

---

## PDF (optional)

Requires the `pdf` extra:

```bash
pip install kulshan[pdf]
```

Generate PDF from an existing HTML report using WeasyPrint.

---

## Excel (optional)

Requires the `excel` extra:

```bash
pip install kulshan[excel]
```

---

## PowerPoint (optional)

Requires the `pptx` extra:

```bash
pip install kulshan[pptx]
```

---

## Account ID Redaction

By default, account IDs in exported reports (HTML, JSON, SARIF, CSV) are redacted to the pattern `XXXX-XXXX-5678` (last 4 digits visible).

To show full account IDs:

```bash
kulshan report -o report.html --show-pii
```

Terminal output always shows full IDs (since it's your local terminal).

---

## Atomic Writes

All file outputs use atomic writes (write to tempfile, then rename). If the process is interrupted during output generation, no partial files are left behind.
