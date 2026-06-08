"""Encryption and secrets scanner, KMS, Secrets Manager, ACM, SSM."""

from datetime import datetime, timezone, timedelta
from .base import BaseScanner, ScanResult, Severity
from ..utils.aws import safe_api_call


class EncryptionScanner(BaseScanner):
    category = "Encryption & Secrets"

    def scan(self) -> ScanResult:
        for region in self.regions:
            self._scan_kms(region)
            self._scan_secrets_manager(region)
            self._scan_acm(region)
            self.advance()
        return ScanResult(findings=self.findings, resources=self.resources, errors=self.errors)

    def _scan_kms(self, region):
        kms = self.session.client("kms", region_name=region)
        keys, err = safe_api_call(kms, "list_keys")
        if err: return
        for key in (keys or {}).get("Keys", []):
            kid = key["KeyId"]
            desc, _ = safe_api_call(kms, "describe_key", KeyId=kid)
            if not desc: continue
            meta = desc.get("KeyMetadata", {})
            if meta.get("KeyManager") != "CUSTOMER": continue
            if meta.get("KeyState") != "Enabled": continue

            rotation, _ = safe_api_call(kms, "get_key_rotation_status", KeyId=kid)
            if rotation and not rotation.get("KeyRotationEnabled"):
                self.add_finding(
                    check_id="ENC-001", title=f"KMS key '{kid[:12]}...' rotation not enabled",
                    severity=Severity.MEDIUM, resource_type="AWS::KMS::Key",
                    resource_id=kid, region=region,
                    description="Customer-managed KMS key does not have automatic rotation.",
                    remediation="Enable automatic key rotation.")

    def _scan_secrets_manager(self, region):
        sm = self.session.client("secretsmanager", region_name=region)
        secrets, err = safe_api_call(sm, "list_secrets")
        if err: return
        for secret in (secrets or {}).get("SecretList", []):
            if not secret.get("RotationEnabled"):
                name = secret.get("Name", "unknown")
                self.add_finding(
                    check_id="ENC-002", title=f"Secret '{name}' has no rotation configured",
                    severity=Severity.MEDIUM, resource_type="AWS::SecretsManager::Secret",
                    resource_id=name, region=region,
                    description="Secret is not automatically rotated.",
                    remediation="Configure automatic rotation with a Lambda function.")

    def _scan_acm(self, region):
        acm = self.session.client("acm", region_name=region)
        certs, err = safe_api_call(acm, "list_certificates")
        if err: return
        now = datetime.now(timezone.utc)
        for cert in (certs or {}).get("CertificateSummaryList", []):
            arn = cert["CertificateArn"]
            detail, _ = safe_api_call(acm, "describe_certificate", CertificateArn=arn)
            if not detail: continue
            c = detail.get("Certificate", {})
            not_after = c.get("NotAfter")
            if not_after:
                if isinstance(not_after, str):
                    not_after = datetime.fromisoformat(not_after)
                if not not_after.tzinfo:
                    not_after = not_after.replace(tzinfo=timezone.utc)
                days_left = (not_after - now).days
                if days_left < 30:
                    domain = c.get("DomainName", "unknown")
                    self.add_finding(
                        check_id="ENC-003", title=f"Certificate for '{domain}' expires in {days_left} days",
                        severity=Severity.HIGH if days_left < 7 else Severity.MEDIUM,
                        resource_type="AWS::ACM::Certificate",
                        resource_id=domain, region=region, resource_arn=arn,
                        description=f"Certificate expires on {not_after.strftime('%Y-%m-%d')}.",
                        remediation="Renew or replace this certificate before expiration.")
