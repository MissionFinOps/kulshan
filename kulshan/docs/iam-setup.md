# Kulshan IAM Setup

Kulshan is read-only. CUR/Data Export workflows use customer-owned billing exports and do not write to AWS.

The current S3-related commands are:

- `kulshan cur s3-check --s3 s3://BILLING_BUCKET_NAME/EXPORT/PREFIX/`: readiness check only. It downloads nothing and runs no analysis.
- `kulshan analyze cost --s3 s3://BILLING_BUCKET_NAME/EXPORT/PREFIX/ --month YYYY-MM`: experimental S3-native cost analysis. It reads the manifest and queries CUR/Data Export Parquet through DuckDB `httpfs`.

The experimental S3-native analysis path does not download the full CUR by default. It requires no Athena workgroup, has no Glue catalog dependency, and has no Athena scanned-data billing for the default evidence workflow. Standard S3 request and transfer charges may still apply.

Local/offline mode remains supported with `kulshan cur validate --path ./cur/` and `kulshan analyze ec2 --cur ./cur/ --month YYYY-MM`. Local validation and local EC2 analysis require no AWS IAM permissions.

## KulshanCurS3ReadOnly Add-On Policy

Replace `BILLING_BUCKET_NAME` and `EXPORT/PREFIX/` with the customer billing export bucket and prefix.

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "ListCurExportPrefix",
      "Effect": "Allow",
      "Action": "s3:ListBucket",
      "Resource": "arn:aws:s3:::BILLING_BUCKET_NAME",
      "Condition": {
        "StringLike": {
          "s3:prefix": [
            "EXPORT/PREFIX/*",
            "EXPORT/PREFIX/"
          ]
        }
      }
    },
    {
      "Sid": "ReadCurExportObjects",
      "Effect": "Allow",
      "Action": "s3:GetObject",
      "Resource": "arn:aws:s3:::BILLING_BUCKET_NAME/EXPORT/PREFIX/*"
    }
  ]
}
```

`kulshan cur s3-check` uses `ListObjectsV2` and `HeadObject` for one manifest and one Parquet object when found. AWS authorizes `HeadObject` with `s3:GetObject`; the readiness check does not download object bodies.

`kulshan analyze cost --s3` uses the same read-only S3 scope to read the manifest and query Parquet through DuckDB `httpfs`. It should be treated as an experimental S3-native analysis path, not as a production-complete product.

## Optional KulshanDataExportsDiscoveryReadOnly Policy

Kulshan discovers modern AWS Data Exports and legacy CUR definitions. The baseline policy therefore includes `bcm-data-exports:GetExport`, `bcm-data-exports:ListExports`, and `cur:DescribeReportDefinitions`. Generate the required export-prefix S3 policy without applying it using `kulshan cur iam --export EXPORT_NAME`:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "ListBillingDataExports",
      "Effect": "Allow",
      "Action": [
        "bcm-data-exports:ListExports",
        "bcm-data-exports:GetExport"
      ],
      "Resource": "*"
    }
  ]
}
```

This is not required for `s3-check` or the current experimental S3-native cost analysis command when the bucket and prefix are already known.

## Optional KMS Decrypt Policy

If the S3 bucket or objects use a customer-managed KMS key, `HeadObject` or Parquet reads through DuckDB `httpfs` may require decrypt permission depending on the encryption setup and account controls.

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "DecryptCurExportObjects",
      "Effect": "Allow",
      "Action": "kms:Decrypt",
      "Resource": "arn:aws:kms:REGION:123456789012:key/KEY_ID",
      "Condition": {
        "StringEquals": {
          "kms:ViaService": "s3.REGION.amazonaws.com"
        }
      }
    }
  ]
}
```

## Admin CLI Verification

Confirm the identity:

```bash
aws sts get-caller-identity
```

Confirm the prefix is listable:

```bash
aws s3api list-objects-v2 \
  --bucket BILLING_BUCKET_NAME \
  --prefix EXPORT/PREFIX/ \
  --max-keys 50
```

Confirm object metadata is readable without downloading data:

```bash
aws s3api head-object \
  --bucket BILLING_BUCKET_NAME \
  --key EXPORT/PREFIX/path/to/Manifest.json

aws s3api head-object \
  --bucket BILLING_BUCKET_NAME \
  --key EXPORT/PREFIX/path/to/file.parquet
```

Then run Kulshan's readiness check:

```bash
kulshan cur s3-check --s3 s3://BILLING_BUCKET_NAME/EXPORT/PREFIX/
```

Run experimental S3-native cost analysis for a billing month:

```bash
kulshan analyze cost --s3 s3://BILLING_BUCKET_NAME/EXPORT/PREFIX/ --month YYYY-MM
```

For local/offline validation, manually copy a small known Parquet object locally and run:

```bash
aws s3 cp s3://BILLING_BUCKET_NAME/EXPORT/PREFIX/path/to/file.parquet ./.kulshan-real-cur-test/file.parquet
kulshan cur validate --path ./.kulshan-real-cur-test/
```

`kulshan cur validate` validates generic CUR readability and should not fail just because EC2 rows are absent. EC2 investigation is one pack, not the validation gate. `kulshan analyze ec2` still uses local files only and can fail clearly when the selected data has no EC2 rows.
## Discovery and least-privilege workflow

1. Run `kulshan cur discover` with the intended payer profile or role.
2. Persist a choice with `kulshan cur select EXPORT_NAME --cost-source hybrid`.
3. Run `kulshan cur iam --export EXPORT_NAME` to generate a policy limited to that bucket and prefix.
4. Have an AWS administrator review and apply it. Kulshan never changes IAM, S3, Data Exports, or CUR configuration.

Customer-managed S3 KMS encryption adds `kms:Decrypt` limited to the discovered key and S3 service context. AWS-managed S3 encryption needs no KMS grant.
