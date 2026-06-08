"""Compute security scanner, EC2, Lambda, EKS."""

import json
from .base import BaseScanner, ScanResult, Severity
from ..utils.aws import safe_api_call

OUTDATED_RUNTIMES = {"python2.7", "python3.6", "python3.7", "nodejs10.x", "nodejs12.x", "dotnetcore2.1", "dotnetcore3.1", "ruby2.5", "ruby2.7", "java8"}
SECRET_PATTERNS = {"password", "secret", "key", "token", "api_key", "apikey", "db_pass", "database_url", "private_key", "aws_secret"}


class ComputeScanner(BaseScanner):
    category = "Compute Security"

    def scan(self) -> ScanResult:
        for region in self.regions:
            self._scan_ec2(region)
            self._scan_lambda(region)
            self._scan_eks(region)
            self.advance()
        return ScanResult(findings=self.findings, resources=self.resources, errors=self.errors)

    def _scan_ec2(self, region):
        ec2 = self.session.client("ec2", region_name=region)
        instances, err = safe_api_call(ec2, "describe_instances")
        if err: return
        for res in (instances or {}).get("Reservations", []):
            for inst in res.get("Instances", []):
                iid = inst["InstanceId"]
                state = inst.get("State", {}).get("Name", "")
                if state != "running": continue

                # IMDSv1 check
                md = inst.get("MetadataOptions", {})
                if md.get("HttpTokens") != "required":
                    self.add_finding(
                        check_id="COMP-001", title=f"EC2 '{iid}' allows IMDSv1 (credential theft risk)",
                        severity=Severity.CRITICAL, resource_type="AWS::EC2::Instance",
                        resource_id=iid, region=region,
                        description="IMDSv1 is vulnerable to SSRF-based credential theft.",
                        remediation="Set HttpTokens to 'required' to enforce IMDSv2.")

                # Public IP
                if inst.get("PublicIpAddress"):
                    self.add_finding(
                        check_id="COMP-002", title=f"EC2 '{iid}' has public IP {inst['PublicIpAddress']}",
                        severity=Severity.HIGH, resource_type="AWS::EC2::Instance",
                        resource_id=iid, region=region,
                        description="Instance is directly reachable from the internet.",
                        remediation="Use private subnets with NAT gateway, or ALB/NLB for public-facing services.")

    def _scan_lambda(self, region):
        lam = self.session.client("lambda", region_name=region)
        funcs, err = safe_api_call(lam, "list_functions")
        if err: return
        for fn in (funcs or {}).get("Functions", []):
            fname = fn["FunctionName"]

            # Secrets in env vars
            env_vars = fn.get("Environment", {}).get("Variables", {})
            for key, val in env_vars.items():
                if any(p in key.lower() for p in SECRET_PATTERNS):
                    self.add_finding(
                        check_id="COMP-003", title=f"Lambda '{fname}' has potential secret in env var '{key}'",
                        severity=Severity.CRITICAL, resource_type="AWS::Lambda::Function",
                        resource_id=fname, region=region,
                        description=f"Environment variable '{key}' may contain a secret.",
                        remediation="Use Secrets Manager or SSM Parameter Store instead of environment variables.")

            # Public invocation
            policy, _ = safe_api_call(lam, "get_policy", FunctionName=fname)
            if policy:
                try:
                    doc = json.loads(policy.get("Policy", "{}"))
                    for stmt in doc.get("Statement", []):
                        principal = stmt.get("Principal", {})
                        if principal == "*" or (isinstance(principal, dict) and principal.get("AWS") == "*"):
                            self.add_finding(
                                check_id="COMP-004", title=f"Lambda '{fname}' allows public invocation",
                                severity=Severity.HIGH, resource_type="AWS::Lambda::Function",
                                resource_id=fname, region=region,
                                description="Anyone can invoke this function.",
                                remediation="Restrict the resource policy to specific principals.")
                except Exception:
                    pass

            # Outdated runtime
            runtime = fn.get("Runtime", "")
            if runtime in OUTDATED_RUNTIMES:
                self.add_finding(
                    check_id="COMP-005", title=f"Lambda '{fname}' uses outdated runtime '{runtime}'",
                    severity=Severity.MEDIUM, resource_type="AWS::Lambda::Function",
                    resource_id=fname, region=region,
                    description=f"Runtime {runtime} is deprecated and may have known vulnerabilities.",
                    remediation="Upgrade to a supported runtime version.")

    def _scan_eks(self, region):
        eks = self.session.client("eks", region_name=region)
        clusters, err = safe_api_call(eks, "list_clusters")
        if err: return
        for name in (clusters or {}).get("clusters", []):
            detail, _ = safe_api_call(eks, "describe_cluster", name=name)
            if not detail: continue
            cluster = detail.get("cluster", {})
            endpoint_access = cluster.get("resourcesVpcConfig", {})
            if endpoint_access.get("endpointPublicAccess") and not endpoint_access.get("publicAccessCidrs", []) == ["0.0.0.0/0"]:
                pass  # has restrictions
            elif endpoint_access.get("endpointPublicAccess"):
                cidrs = endpoint_access.get("publicAccessCidrs", [])
                if "0.0.0.0/0" in cidrs:
                    self.add_finding(
                        check_id="COMP-006", title=f"EKS cluster '{name}' API is public to 0.0.0.0/0",
                        severity=Severity.HIGH, resource_type="AWS::EKS::Cluster",
                        resource_id=name, region=region,
                        description="Kubernetes API server is accessible from any IP.",
                        remediation="Restrict publicAccessCidrs to trusted IPs or disable public endpoint.")
