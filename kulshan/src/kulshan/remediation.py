"""Central remediation snippet engine.

Enriches canonical findings with actionable fix commands based on pack + kind.
Templates use {resource_id}, {region}, {resource_arn} placeholders filled from
the finding dict at enrichment time.
"""
from __future__ import annotations

from typing import Dict, List, Optional


# ---------------------------------------------------------------------------
# Remediation snippet templates: pack → kind → template
# ---------------------------------------------------------------------------

SNIPPETS: Dict[str, Dict[str, str]] = {
    "sweep": {
        "unused-ebs-volume": "aws ec2 delete-volume --volume-id {resource_id} --region {region}",
        "unused-elastic-ip": "aws ec2 release-address --allocation-id {resource_id} --region {region}",
        "orphaned-snapshot": "aws ec2 delete-snapshot --snapshot-id {resource_id} --region {region}",
        "unused-nat-gateway": "aws ec2 delete-nat-gateway --nat-gateway-id {resource_id} --region {region}",
        "idle-load-balancer": "aws elbv2 delete-load-balancer --load-balancer-arn {resource_arn} --region {region}",
        "stopped-instance": "aws ec2 terminate-instances --instance-ids {resource_id} --region {region}",
        "unused-eni": "aws ec2 delete-network-interface --network-interface-id {resource_id} --region {region}",
    },
    "security": {
        "root-mfa-disabled": "# Enable MFA on root: AWS Console → IAM → Security credentials → Activate MFA",
        "user-no-mfa": "# Enforce MFA for user {resource_id}:\naws iam create-virtual-mfa-device --virtual-mfa-device-name {resource_id}-mfa --outfile /tmp/qr.png --bootstrap-method QRCodePNG",
        "stale-access-key": "aws iam update-access-key --user-name {resource_id} --access-key-id ACCESS_KEY_ID --status Inactive --region {region}",
        "admin-policy-attached": "# Review and scope down permissions for {resource_id}\naws iam list-attached-user-policies --user-name {resource_id}",
        "public-s3-bucket": "aws s3api put-public-access-block --bucket {resource_id} --public-access-block-configuration BlockPublicAcls=true,IgnorePublicAcls=true,BlockPublicPolicy=true,RestrictPublicBuckets=true",
        "unencrypted-rds": "aws rds modify-db-instance --db-instance-identifier {resource_id} --storage-encrypted --apply-immediately --region {region}",
        "open-ssh": "aws ec2 revoke-security-group-ingress --group-id {resource_id} --protocol tcp --port 22 --cidr 0.0.0.0/0 --region {region}",
        "open-rdp": "aws ec2 revoke-security-group-ingress --group-id {resource_id} --protocol tcp --port 3389 --cidr 0.0.0.0/0 --region {region}",
        "no-cloudtrail": "aws cloudtrail create-trail --name kulshan-recommended --s3-bucket-name YOUR-BUCKET --is-multi-region-trail --region {region}",
        "no-guardduty": "aws guardduty create-detector --enable --region {region}",
        "imdsv1-enabled": "aws ec2 modify-instance-metadata-options --instance-id {resource_id} --http-tokens required --http-endpoint enabled --region {region}",
        "no-vpc-flow-logs": "aws ec2 create-flow-logs --resource-type VPC --resource-ids {resource_id} --traffic-type ALL --log-destination-type cloud-watch-logs --region {region}",
    },
    "cost": {
        "anomaly-detected": "# Review anomaly in AWS Cost Explorer:\n# https://console.aws.amazon.com/cost-management/home#/cost-explorer",
        "idle-resource": "# Review resource utilization and consider right-sizing or termination",
        "reserved-instance-opportunity": "# Consider purchasing Reserved Instances or Savings Plans:\n# https://console.aws.amazon.com/cost-management/home#/reservations",
    },
    "dr": {
        "no-backup": "aws backup create-backup-plan --backup-plan '{{\"BackupPlanName\":\"daily-backup\",\"Rules\":[{{\"RuleName\":\"daily\",\"TargetBackupVaultName\":\"Default\",\"ScheduleExpression\":\"cron(0 5 ? * * *)\",\"Lifecycle\":{{\"DeleteAfterDays\":30}}}}]}}' --region {region}",
        "single-az": "# Enable Multi-AZ for {resource_id}:\naws rds modify-db-instance --db-instance-identifier {resource_id} --multi-az --apply-immediately --region {region}",
        "no-cross-region-backup": "# Configure cross-region backup copy rule in AWS Backup",
    },
    "age": {
        "eol-runtime": "# Upgrade runtime for {resource_id} to a supported version",
        "expiring-certificate": "aws acm renew-certificate --certificate-arn {resource_arn} --region {region}",
        "stale-ami": "aws ec2 deregister-image --image-id {resource_id} --region {region}",
    },
    "drift": {
        "stack-drifted": "aws cloudformation detect-stack-drift --stack-name {resource_id} --region {region}\n# Then: aws cloudformation describe-stack-resource-drifts --stack-name {resource_id} --region {region}",
        "unmanaged-resource": "# Import resource into CloudFormation or Terraform state",
    },
    "tag": {
        "untagged-resource": "aws resourcegroupstaggingapi tag-resources --resource-arn-list {resource_arn} --tags Environment=unknown,Owner=unknown --region {region}",
        "missing-cost-allocation": "# Add cost allocation tags: Project, Environment, Owner, Team",
    },
    "pulse": {
        "no-alarm": "# Create CloudWatch alarm for {resource_id}:\naws cloudwatch put-metric-alarm --alarm-name {resource_id}-health --metric-name CPUUtilization --namespace AWS/EC2 --statistic Average --period 300 --threshold 90 --comparison-operator GreaterThanThreshold --evaluation-periods 2 --region {region}",
        "no-logging": "# Enable logging for {resource_id}",
    },
    "limit": {
        "quota-near-limit": "aws service-quotas request-service-quota-increase --service-code {service} --quota-code {quota_code} --desired-value NEW_VALUE --region {region}",
        "scaling-blocked": "# Request quota increase before scaling event",
    },
    "topo": {
        "cidr-overlap": "# Review VPC CIDR allocation for {resource_id} — overlapping ranges prevent peering",
        "route-asymmetry": "# Review route tables for {resource_id} to fix asymmetric routing",
    },
}


def enrich_findings(findings: List[dict]) -> List[dict]:
    """Add remediation_snippet to each finding based on pack + kind.

    Modifies findings in-place and returns them. Findings without a matching
    template get an empty string.
    """
    for finding in findings:
        pack = finding.get("pack", "")
        kind = finding.get("kind", "")
        template = SNIPPETS.get(pack, {}).get(kind, "")

        if template:
            # Fill placeholders from finding fields
            snippet = template.format(
                resource_id=finding.get("resource_id", finding.get("id", "UNKNOWN")),
                resource_arn=finding.get("resource_arn", ""),
                region=finding.get("region", "us-east-1"),
                service=finding.get("metadata", {}).get("service", "ec2"),
                quota_code=finding.get("metadata", {}).get("quota_code", "L-UNKNOWN"),
            )
            finding["remediation_snippet"] = snippet
        else:
            # Fall back to recommended_action if present
            finding["remediation_snippet"] = finding.get("recommended_action", "")

    return findings
