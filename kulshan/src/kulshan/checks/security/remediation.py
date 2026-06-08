"""Remediation Code Generator, Terraform/boto3 fix templates for each finding."""

from typing import Dict, List
from .scanner.base import Finding

TERRAFORM_TEMPLATES = {
    "IAM-001": '''# Fix: Enable MFA on root account
# This must be done manually via the AWS Console:
# 1. Sign in as root: https://console.aws.amazon.com/
# 2. Go to IAM > Security credentials
# 3. Activate MFA
# Terraform cannot manage root MFA.''',

    "IAM-003": '''# Fix: Enforce MFA for IAM user "{resource_id}"
resource "aws_iam_user_policy" "{resource_id}_mfa_enforce" {{
  name   = "enforce-mfa"
  user   = "{resource_id}"
  policy = jsonencode({{
    Version = "2012-10-17"
    Statement = [{{
      Sid       = "DenyAllExceptMFA"
      Effect    = "Deny"
      NotAction = ["iam:CreateVirtualMFADevice", "iam:EnableMFADevice",
                   "iam:GetUser", "iam:ListMFADevices", "iam:ListVirtualMFADevices",
                   "iam:ResyncMFADevice", "sts:GetSessionToken"]
      Resource  = "*"
      Condition = {{ Bool = {{ "aws:MultiFactorAuthPresent" = "false" }} }}
    }}]
  }})
}}''',

    "IAM-004": '''# Fix: Rotate access key for user "{resource_id}"
# boto3 script:
# import boto3
# iam = boto3.client('iam')
# new_key = iam.create_access_key(UserName='{resource_id}')
# # Update applications with new key, then:
# iam.delete_access_key(UserName='{resource_id}', AccessKeyId='OLD_KEY_ID')''',

    "NET-002": '''# Fix: Restrict SSH access on security group "{resource_id}"
resource "aws_security_group_rule" "restrict_ssh_{resource_id}" {{
  type              = "ingress"
  from_port         = 22
  to_port           = 22
  protocol          = "tcp"
  cidr_blocks       = ["10.0.0.0/8"]  # Replace with your VPN/office CIDR
  security_group_id = "{resource_id}"
  description       = "SSH from internal network only"
}}
# Also remove the 0.0.0.0/0 rule for port 22''',

    "NET-003": '''# Fix: Remove public database port access on "{resource_id}"
# CRITICAL: Database ports should NEVER be open to the internet.
# Remove the 0.0.0.0/0 ingress rule and restrict to application security groups:
resource "aws_security_group_rule" "db_access_{resource_id}" {{
  type                     = "ingress"
  from_port                = 5432  # Adjust port for your DB
  to_port                  = 5432
  protocol                 = "tcp"
  source_security_group_id = "sg-APP_SG_ID"  # App tier SG only
  security_group_id        = "{resource_id}"
}}''',

    "NET-005": '''# Fix: Enable VPC flow logs for "{resource_id}"
resource "aws_flow_log" "{resource_id}_flow_log" {{
  vpc_id          = "{resource_id}"
  traffic_type    = "ALL"
  log_destination = aws_cloudwatch_log_group.flow_logs.arn
  iam_role_arn    = aws_iam_role.flow_log_role.arn
}}

resource "aws_cloudwatch_log_group" "flow_logs" {{
  name              = "/aws/vpc/flow-logs/{resource_id}"
  retention_in_days = 90
}}''',

    "DATA-001": '''# Fix: Enable S3 Block Public Access for bucket "{resource_id}"
resource "aws_s3_bucket_public_access_block" "{resource_id}" {{
  bucket                  = "{resource_id}"
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}}''',

    "DATA-003": '''# Fix: Enable default encryption for S3 bucket "{resource_id}"
resource "aws_s3_bucket_server_side_encryption_configuration" "{resource_id}" {{
  bucket = "{resource_id}"
  rule {{
    apply_server_side_encryption_by_default {{
      sse_algorithm = "aws:kms"
    }}
    bucket_key_enabled = true
  }}
}}''',

    "DATA-005": '''# Fix: Disable public access for RDS instance "{resource_id}"
resource "aws_db_instance" "{resource_id}" {{
  # ... existing config ...
  publicly_accessible = false
}}
# Note: This requires a reboot. Plan a maintenance window.''',

    "COMP-001": '''# Fix: Enforce IMDSv2 on EC2 instance "{resource_id}"
resource "aws_instance" "{resource_id}" {{
  # ... existing config ...
  metadata_options {{
    http_tokens   = "required"  # Enforces IMDSv2
    http_endpoint = "enabled"
  }}
}}
# boto3 quick fix:
# ec2.modify_instance_metadata_options(
#     InstanceId='{resource_id}',
#     HttpTokens='required',
#     HttpEndpoint='enabled')''',

    "LOG-001": '''# Fix: Create multi-region CloudTrail
resource "aws_cloudtrail" "main" {{
  name                       = "kulshan-recommended-trail"
  s3_bucket_name             = aws_s3_bucket.cloudtrail.id
  is_multi_region_trail      = true
  enable_log_file_validation = true
  include_global_service_events = true
}}''',

    "LOG-005": '''# Fix: Enable GuardDuty
resource "aws_guardduty_detector" "main" {{
  enable = true
  finding_publishing_frequency = "FIFTEEN_MINUTES"
}}''',

    "ENC-001": '''# Fix: Enable KMS key rotation for "{resource_id}"
resource "aws_kms_key" "{resource_id}" {{
  # ... existing config ...
  enable_key_rotation = true
}}
# boto3 quick fix:
# kms.enable_key_rotation(KeyId='{resource_id}')''',
}

BOTO3_TEMPLATES = {
    "COMP-001": '''import boto3
ec2 = boto3.client('ec2', region_name='{region}')
ec2.modify_instance_metadata_options(
    InstanceId='{resource_id}',
    HttpTokens='required',
    HttpEndpoint='enabled'
)
print(f"IMDSv2 enforced on {resource_id}")''',

    "DATA-001": '''import boto3
s3 = boto3.client('s3')
s3.put_public_access_block(
    Bucket='{resource_id}',
    PublicAccessBlockConfiguration={{
        'BlockPublicAcls': True,
        'IgnorePublicAcls': True,
        'BlockPublicPolicy': True,
        'RestrictPublicBuckets': True
    }}
)
print(f"Public access blocked on {resource_id}")''',

    "ENC-001": '''import boto3
kms = boto3.client('kms', region_name='{region}')
kms.enable_key_rotation(KeyId='{resource_id}')
print(f"Key rotation enabled on {resource_id}")''',
}


def generate_remediation(findings: List[Finding], fmt: str = "terraform") -> str:
    """Generate remediation code for all findings."""
    templates = TERRAFORM_TEMPLATES if fmt == "terraform" else BOTO3_TEMPLATES
    output_parts = []
    seen = set()

    output_parts.append(f"# Kulshan, Security Remediation Plan ({fmt})")
    output_parts.append(f"# Generated for {len(findings)} findings\n")

    for f in findings:
        key = f"{f.check_id}:{f.resource_id}"
        if key in seen:
            continue
        seen.add(key)

        template = templates.get(f.check_id)
        if template:
            code = template.format(
                resource_id=f.resource_id.replace("-", "_").replace(":", "_").replace("/", "_"),
                region=f.region,
            )
            output_parts.append(f"# [{f.severity.value}] {f.title}")
            output_parts.append(f"# Resource: {f.resource_id} ({f.region})")
            output_parts.append(code)
            output_parts.append("")

    if len(output_parts) <= 2:
        output_parts.append("# No automated remediation templates available for current findings.")

    return "\n".join(output_parts)
