# Kulshan IAM Setup

Kulshan is read-only. The `kulshan cur s3-check` command is an S3 readiness check for CUR/Data Export onboarding. It downloads nothing, runs no analysis, does not query Athena, and does not use Glue. It calls only `s3:ListBucket` and `s3:GetObject`-class metadata checks through `HeadObject`.

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
      "Sid": "ReadCurExportObjectMetadata",
      "Effect": "Allow",
      "Action": "s3:GetObject",
      "Resource": "arn:aws:s3:::BILLING_BUCKET_NAME/EXPORT/PREFIX/*"
    }
  ]
}
```

`kulshan cur s3-check` uses `HeadObject` for one manifest and one Parquet object when found. AWS authorizes `HeadObject` with `s3:GetObject`; the command does not download object bodies.

## Optional KulshanDataExportsDiscoveryReadOnly Policy

Kulshan does not currently discover AWS Data Exports. If a future workflow adds discovery, an administrator can consider a separate read-only policy like this:

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

This is not required for the current `s3-check` command.

## Optional KMS Decrypt Policy

If the S3 bucket or objects use a customer-managed KMS key, `HeadObject` may require decrypt permission depending on the encryption setup and account controls.

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

If the check succeeds, manually copy a small known Parquet object locally and run local validation:

```bash
aws s3 cp s3://BILLING_BUCKET_NAME/EXPORT/PREFIX/path/to/file.parquet ./.kulshan-real-cur-test/file.parquet
kulshan cur validate --path ./.kulshan-real-cur-test/
```

Current local analysis still requires local Parquet files. `s3-check` does not make `kulshan investigate ec2` accept `s3://` paths.