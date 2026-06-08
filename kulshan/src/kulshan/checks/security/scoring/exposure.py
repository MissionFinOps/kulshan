"""Public exposure score, single number for internet-facing risk."""

from typing import Dict, List, Any
from ..scanner.base import Finding, Severity


def calculate_exposure_score(findings: List[Finding], resources: Dict[str, Any]) -> Dict:
    """Calculate a 0-100 public exposure score (100 = fully exposed, 0 = locked down)."""
    exposure_points = 0
    max_points = 100
    details = []

    # SGs open to internet (any port)
    open_all = sum(1 for f in findings if f.check_id == "NET-001")
    if open_all:
        pts = min(25, open_all * 15)
        exposure_points += pts
        details.append(f"{open_all} security group(s) open ALL ports to internet (+{pts})")

    # Management ports exposed
    mgmt_exposed = sum(1 for f in findings if f.check_id == "NET-002")
    if mgmt_exposed:
        pts = min(20, mgmt_exposed * 4)
        exposure_points += pts
        details.append(f"{mgmt_exposed} management port(s) exposed to internet (+{pts})")

    # Database ports exposed
    db_exposed = sum(1 for f in findings if f.check_id == "NET-003")
    if db_exposed:
        pts = min(20, db_exposed * 8)
        exposure_points += pts
        details.append(f"{db_exposed} database port(s) exposed to internet (+{pts})")

    # Public S3 buckets
    public_s3 = sum(1 for f in findings if f.check_id == "DATA-002")
    if public_s3:
        pts = min(15, public_s3 * 10)
        exposure_points += pts
        details.append(f"{public_s3} public S3 bucket(s) (+{pts})")

    # Public RDS
    public_rds = sum(1 for f in findings if f.check_id == "DATA-005")
    if public_rds:
        pts = min(15, public_rds * 10)
        exposure_points += pts
        details.append(f"{public_rds} publicly accessible RDS instance(s) (+{pts})")

    # Public EBS/RDS snapshots
    public_snaps = sum(1 for f in findings if f.check_id in ("DATA-007", "DATA-009"))
    if public_snaps:
        pts = min(10, public_snaps * 5)
        exposure_points += pts
        details.append(f"{public_snaps} public snapshot(s) (+{pts})")

    # EC2 with public IPs
    public_ec2 = sum(1 for f in findings if f.check_id == "COMP-002")
    if public_ec2:
        pts = min(10, public_ec2 * 2)
        exposure_points += pts
        details.append(f"{public_ec2} EC2 instance(s) with public IPs (+{pts})")

    # IMDSv1 (credential theft vector)
    imdsv1 = sum(1 for f in findings if f.check_id == "COMP-001")
    if imdsv1:
        pts = min(10, imdsv1 * 3)
        exposure_points += pts
        details.append(f"{imdsv1} EC2 instance(s) with IMDSv1 (+{pts})")

    # Public Lambda
    public_lambda = sum(1 for f in findings if f.check_id == "COMP-004")
    if public_lambda:
        pts = min(10, public_lambda * 5)
        exposure_points += pts
        details.append(f"{public_lambda} publicly invocable Lambda function(s) (+{pts})")

    # EKS public API
    public_eks = sum(1 for f in findings if f.check_id == "COMP-006")
    if public_eks:
        pts = min(10, public_eks * 5)
        exposure_points += pts
        details.append(f"{public_eks} EKS cluster(s) with public API (+{pts})")

    # Subnets auto-assigning public IPs
    auto_pub = sum(1 for f in findings if f.check_id == "NET-006")
    if auto_pub:
        pts = min(5, auto_pub)
        exposure_points += pts
        details.append(f"{auto_pub} subnet(s) auto-assigning public IPs (+{pts})")

    # No details = clean
    if not details:
        details.append("No public exposure detected")

    score = min(100, exposure_points)
    if score <= 10:
        rating = "Minimal"
        color = "green"
    elif score <= 30:
        rating = "Low"
        color = "green"
    elif score <= 50:
        rating = "Moderate"
        color = "yellow"
    elif score <= 70:
        rating = "High"
        color = "dark_orange"
    else:
        rating = "Critical"
        color = "red"

    return {
        "score": score,
        "rating": rating,
        "color": color,
        "details": details,
    }
