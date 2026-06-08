"""Compliance mapping, tag findings with CIS, NIST, SOC2 controls."""

# Mapping: check_id -> list of (framework, control_id, control_name)
COMPLIANCE_MAP = {
    "IAM-001": [("CIS", "1.5", "Ensure MFA is enabled for root account"),
                ("NIST", "IA-2(1)", "Multi-factor Authentication")],
    "IAM-002": [("CIS", "1.4", "Ensure no root access keys exist"),
                ("NIST", "IA-2", "Identification and Authentication")],
    "IAM-003": [("CIS", "1.10", "Ensure MFA is enabled for all IAM users with console access"),
                ("SOC2", "CC6.1", "Logical Access Security")],
    "IAM-004": [("CIS", "1.14", "Ensure access keys are rotated every 90 days"),
                ("NIST", "IA-5(1)", "Password-Based Authentication")],
    "IAM-005": [("CIS", "1.16", "Ensure IAM policies with full admin are not attached"),
                ("NIST", "AC-6", "Least Privilege")],
    "IAM-007": [("CIS", "1.16", "Cross-account trust"),
                ("NIST", "AC-17", "Remote Access")],
    "IAM-009": [("CIS", "1.12", "Ensure credentials unused for 90 days are disabled"),
                ("NIST", "AC-2(3)", "Disable Inactive Accounts")],
    "IAM-010": [("CIS", "1.8", "Ensure IAM password policy requires minimum length"),
                ("NIST", "IA-5(1)", "Password-Based Authentication")],
    "NET-001": [("CIS", "5.2", "Ensure no security groups allow ingress from 0.0.0.0/0"),
                ("NIST", "SC-7", "Boundary Protection")],
    "NET-002": [("CIS", "5.2", "Ensure no security groups allow ingress to admin ports"),
                ("NIST", "SC-7(5)", "Deny by Default")],
    "NET-005": [("CIS", "3.9", "Ensure VPC flow logging is enabled"),
                ("NIST", "AU-12", "Audit Generation"),
                ("SOC2", "CC7.2", "System Monitoring")],
    "DATA-001": [("CIS", "2.1.5", "Ensure S3 Block Public Access is enabled"),
                 ("NIST", "AC-3", "Access Enforcement")],
    "DATA-002": [("CIS", "2.1.5", "Ensure S3 buckets are not publicly accessible"),
                 ("SOC2", "CC6.6", "System Boundaries")],
    "DATA-003": [("CIS", "2.1.1", "Ensure S3 bucket default encryption is enabled"),
                 ("NIST", "SC-28", "Protection of Information at Rest")],
    "DATA-005": [("CIS", "2.3.1", "Ensure RDS instances are not publicly accessible"),
                 ("NIST", "SC-7", "Boundary Protection")],
    "DATA-006": [("CIS", "2.3.1", "Ensure RDS encryption is enabled"),
                 ("NIST", "SC-28", "Protection of Information at Rest")],
    "COMP-001": [("CIS", "5.6", "Ensure EC2 instance metadata service v2 is enabled"),
                 ("NIST", "SC-7", "Boundary Protection")],
    "LOG-001": [("CIS", "3.1", "Ensure CloudTrail is enabled in all regions"),
                ("NIST", "AU-2", "Audit Events"),
                ("SOC2", "CC7.2", "System Monitoring")],
    "LOG-002": [("CIS", "3.2", "Ensure CloudTrail log file validation is enabled"),
                ("NIST", "AU-10", "Non-repudiation")],
    "LOG-005": [("CIS", "4.15", "Ensure GuardDuty is enabled"),
                ("NIST", "SI-4", "Information System Monitoring")],
    "LOG-007": [("CIS", "3.5", "Ensure AWS Config is enabled"),
                ("NIST", "CM-8", "Information System Component Inventory")],
    "LOG-009": [("CIS", "1.20", "Ensure IAM Access Analyzer is enabled"),
                ("NIST", "AC-6(3)", "Network Access to Privileged Commands")],
    "ENC-001": [("CIS", "3.8", "Ensure rotation for customer-created CMKs is enabled"),
                ("NIST", "SC-12", "Cryptographic Key Management")],
}


def get_compliance_tags(check_id: str):
    """Get compliance framework tags for a finding."""
    return COMPLIANCE_MAP.get(check_id, [])


def compliance_summary(findings):
    """Summarize compliance coverage by framework."""
    frameworks = {}
    for f in findings:
        tags = get_compliance_tags(f.check_id)
        for framework, control_id, control_name in tags:
            if framework not in frameworks:
                frameworks[framework] = {"total_controls": 0, "failing": 0, "controls": {}}
            key = f"{control_id}: {control_name}"
            if key not in frameworks[framework]["controls"]:
                frameworks[framework]["controls"][key] = {"status": "FAIL", "findings": []}
                frameworks[framework]["total_controls"] += 1
                frameworks[framework]["failing"] += 1
            frameworks[framework]["controls"][key]["findings"].append(f.check_id)
    return frameworks
