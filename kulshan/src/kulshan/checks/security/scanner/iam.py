"""IAM security scanner, identity and access checks."""

import json
import csv
import io
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Any
from .base import BaseScanner, ScanResult, Severity
from ..utils.aws import safe_api_call


class IAMScanner(BaseScanner):
    category = "Identity & Access"

    def _safe_statements(self, doc) -> list:
        """Safely extract Statement list from a policy document."""
        if isinstance(doc, str):
            try:
                import json as _json
                doc = _json.loads(doc)
            except Exception:
                return []
        if not isinstance(doc, dict):
            return []
        stmts = doc.get("Statement", [])
        if isinstance(stmts, dict):
            return [stmts]
        if isinstance(stmts, str):
            return []
        return [s for s in stmts if isinstance(s, dict)]


    def scan(self) -> ScanResult:
        iam = self.session.client("iam", region_name="us-east-1")

        # Collect IAM data
        self.advance()
        auth_details, err = safe_api_call(iam, "get_account_authorization_details",
            Filter=["User", "Role", "Group", "LocalManagedPolicy", "AWSManagedPolicy"])
        if err:
            self.errors.append(f"IAM auth details: {err}")
            auth_details = {}

        self.advance()
        summary, err = safe_api_call(iam, "get_account_summary")
        summary_map = (summary or {}).get("SummaryMap", {})

        self.advance()
        # Generate and fetch credential report
        try:
            iam.generate_credential_report()
            import time; time.sleep(2)
            cred_report_raw, _ = safe_api_call(iam, "get_credential_report")
            cred_report = self._parse_credential_report(cred_report_raw) if cred_report_raw else []
        except Exception:
            cred_report = []

        self.advance()
        password_policy, pp_err = safe_api_call(iam, "get_account_password_policy")

        self.advance()
        mfa_devices, _ = safe_api_call(iam, "list_virtual_mfa_devices")

        users = auth_details.get("UserDetailList", [])
        roles = auth_details.get("RoleDetailList", [])
        groups = auth_details.get("GroupDetailList", [])
        policies = auth_details.get("Policies", [])

        self.resources = {
            "users": users, "roles": roles, "groups": groups,
            "policies": policies, "credential_report": cred_report,
            "summary": summary_map,
        }

        # Run checks
        self._check_root_account(cred_report, summary_map)
        self._check_users_without_mfa(cred_report)
        self._check_stale_access_keys(cred_report)
        self._check_admin_policies(users, roles, groups, policies)
        self._check_privilege_escalation(users, roles, policies)
        self._check_cross_account_trusts(roles)
        self._check_wildcard_permissions(users, roles, policies)
        self._check_unused_users(cred_report)
        self._check_password_policy(password_policy, pp_err)

        # Checks merged from awsperm. Service-last-accessed is slow, so keep it in deep mode.
        if getattr(self, "deep", False):
            self._check_service_last_accessed(roles)
        self._check_access_analyzer()

        return ScanResult(findings=self.findings, resources=self.resources, errors=self.errors)

    def _parse_credential_report(self, raw) -> List[Dict]:
        content = raw.get("Content", b"").decode("utf-8")
        reader = csv.DictReader(io.StringIO(content))
        return list(reader)

    def _check_root_account(self, cred_report, summary):
        for row in cred_report:
            if row.get("user") == "<root_account>":
                if row.get("mfa_active", "false") != "true":
                    self.add_finding(
                        check_id="IAM-001", title="Root account MFA not enabled",
                        severity=Severity.CRITICAL, resource_type="AWS::IAM::Root",
                        resource_id="root", description="The root account does not have MFA enabled. This is the highest privilege account.",
                        remediation="Enable MFA on the root account immediately via the AWS Console.")
                if row.get("access_key_1_active", "false") == "true" or row.get("access_key_2_active", "false") == "true":
                    self.add_finding(
                        check_id="IAM-002", title="Root account has active access keys",
                        severity=Severity.CRITICAL, resource_type="AWS::IAM::Root",
                        resource_id="root", description="Root account has active access keys. These should be deleted.",
                        remediation="Delete root access keys and use IAM users/roles instead.")

    def _check_users_without_mfa(self, cred_report):
        for row in cred_report:
            user = row.get("user", "")
            if user == "<root_account>": continue
            if row.get("password_enabled", "false") == "true" and row.get("mfa_active", "false") != "true":
                self.add_finding(
                    check_id="IAM-003", title=f"User '{user}' has console access without MFA",
                    severity=Severity.CRITICAL, resource_type="AWS::IAM::User",
                    resource_id=user, resource_arn=row.get("arn", ""),
                    description=f"IAM user {user} can log into the console but has no MFA device.",
                    remediation="Enable MFA for this user or disable console access.")

    def _check_stale_access_keys(self, cred_report):
        now = datetime.now(timezone.utc)
        for row in cred_report:
            user = row.get("user", "")
            if user == "<root_account>": continue
            for key_num in ["1", "2"]:
                if row.get(f"access_key_{key_num}_active", "false") == "true":
                    last_rotated = row.get(f"access_key_{key_num}_last_rotated", "N/A")
                    if last_rotated not in ("N/A", "not_supported"):
                        try:
                            rotated_date = datetime.fromisoformat(last_rotated.replace("+00:00", "+00:00"))
                            if not rotated_date.tzinfo:
                                rotated_date = rotated_date.replace(tzinfo=timezone.utc)
                            age_days = (now - rotated_date).days
                            if age_days > 90:
                                self.add_finding(
                                    check_id="IAM-004", title=f"User '{user}' access key {key_num} is {age_days} days old",
                                    severity=Severity.CRITICAL if age_days > 365 else Severity.HIGH,
                                    resource_type="AWS::IAM::AccessKey", resource_id=f"{user}/key{key_num}",
                                    resource_arn=row.get("arn", ""),
                                    description=f"Access key has not been rotated in {age_days} days.",
                                    remediation="Rotate this access key and update applications using it.")
                        except Exception:
                            pass

    def _check_admin_policies(self, users, roles, groups, policies):
        admin_policy_arns = set()
        for policy in policies:
            for version in policy.get("PolicyVersionList", []):
                if version.get("IsDefaultVersion"):
                    doc = version.get("Document", {})
                    if isinstance(doc, str):
                        doc = json.loads(doc)
                    if self._is_admin_policy(doc):
                        admin_policy_arns.add(policy["Arn"])

        for user in users:
            for ap in user.get("AttachedManagedPolicies", []):
                if ap["PolicyArn"] in admin_policy_arns or "AdministratorAccess" in ap.get("PolicyName", ""):
                    self.add_finding(
                        check_id="IAM-005", title=f"User '{user['UserName']}' has admin-equivalent policy",
                        severity=Severity.CRITICAL, resource_type="AWS::IAM::User",
                        resource_id=user["UserName"], resource_arn=user.get("Arn", ""),
                        description=f"Policy '{ap['PolicyName']}' grants full admin access.",
                        remediation="Apply least-privilege: scope down permissions to what is actually needed.")
            for ip in user.get("UserPolicyList", []):
                doc = ip.get("PolicyDocument", {})
                if isinstance(doc, str):
                    try: doc = json.loads(doc)
                    except Exception: continue
                if self._is_admin_policy(doc):
                    self.add_finding(
                        check_id="IAM-005", title=f"User '{user['UserName']}' has inline admin policy",
                        severity=Severity.CRITICAL, resource_type="AWS::IAM::User",
                        resource_id=user["UserName"], resource_arn=user.get("Arn", ""),
                        remediation="Remove inline admin policy and use scoped managed policies.")

    def _is_admin_policy(self, doc: Dict) -> bool:
        if isinstance(doc, str):
            try:
                doc = json.loads(doc)
            except Exception:
                return False
        stmts = doc.get("Statement", [])
        if isinstance(stmts, dict):
            stmts = [stmts]
        if isinstance(stmts, str):
            return False
        for stmt in stmts:
            if not isinstance(stmt, dict):
                continue
            if stmt.get("Effect") == "Allow":
                actions = stmt.get("Action", [])
                resources = stmt.get("Resource", [])
                if isinstance(actions, str): actions = [actions]
                if isinstance(resources, str): resources = [resources]
                if "*" in actions and "*" in resources:
                    return True
        return False


    def _safe_statements(self, doc) -> list:
        """Safely extract Statement list from a policy document."""
        if isinstance(doc, str):
            try:
                doc = json.loads(doc)
            except Exception:
                return []
        if not isinstance(doc, dict):
            return []
        stmts = doc.get("Statement", [])
        if isinstance(stmts, dict):
            return [stmts]
        if isinstance(stmts, list):
            return [s for s in stmts if isinstance(s, dict)]
        return []

    def _check_privilege_escalation(self, users, roles, policies):
        ESCALATION_ACTIONS = {
            "iam:CreatePolicyVersion", "iam:SetDefaultPolicyVersion", "iam:PassRole",
            "iam:AttachUserPolicy", "iam:AttachRolePolicy", "iam:PutUserPolicy",
            "iam:PutRolePolicy", "iam:AddUserToGroup", "iam:CreateLoginProfile",
            "iam:UpdateLoginProfile",
        }
        for user in users:
            user_actions = self._get_all_actions(user, policies)
            escalation = user_actions & ESCALATION_ACTIONS
            if len(escalation) >= 2 and "iam:PassRole" in escalation:
                self.add_finding(
                    check_id="IAM-006", title=f"User '{user['UserName']}' has privilege escalation potential",
                    severity=Severity.CRITICAL, resource_type="AWS::IAM::User",
                    resource_id=user["UserName"], resource_arn=user.get("Arn", ""),
                    description=f"Has iam:PassRole plus {escalation - {'iam:PassRole'}}",
                    remediation="Remove iam:PassRole or restrict which roles can be passed.")

    def _safe_stmts(self, doc) -> list:
        if isinstance(doc, str):
            try: doc = json.loads(doc)
            except Exception: return []
        if not isinstance(doc, dict): return []
        stmts = doc.get("Statement", [])
        if isinstance(stmts, dict): stmts = [stmts]
        if not isinstance(stmts, list): return []
        return [s for s in stmts if isinstance(s, dict)]

    def _get_all_actions(self, entity, policies) -> set:
        actions = set()
        for ip in entity.get("UserPolicyList", []) + entity.get("RolePolicyList", []):
            doc = ip.get("PolicyDocument", {})
            if isinstance(doc, str):
                try: doc = json.loads(doc)
                except Exception: continue
            for stmt in self._safe_stmts(doc):
                if stmt.get("Effect") == "Allow":
                    a = stmt.get("Action", [])
                    if isinstance(a, str): a = [a]
                    actions.update(a)
        for ap in entity.get("AttachedManagedPolicies", []):
            for p in policies:
                if p["Arn"] == ap["PolicyArn"]:
                    for v in p.get("PolicyVersionList", []):
                        if v.get("IsDefaultVersion"):
                            doc = v.get("Document", {})
                            if isinstance(doc, str):
                                try: doc = json.loads(doc)
                                except Exception: continue
                            for stmt in self._safe_stmts(doc):
                                if stmt.get("Effect") == "Allow":
                                    a = stmt.get("Action", [])
                                    if isinstance(a, str): a = [a]
                                    actions.update(a)
        return actions

    def _check_cross_account_trusts(self, roles):
        for role in roles:
            trust = role.get("AssumeRolePolicyDocument", {})
            for stmt in self._safe_statements(trust):
                if stmt.get("Effect") != "Allow": continue
                principals = stmt.get("Principal", {})
                if isinstance(principals, str): principals = {"AWS": [principals]}
                aws_principals = principals.get("AWS", [])
                if isinstance(aws_principals, str): aws_principals = [aws_principals]
                for p in aws_principals:
                    if ":root" in p or (":iam::" in p and "role/" not in p.lower()):
                        conditions = stmt.get("Condition", {})
                        has_external_id = any("ExternalId" in str(v) for v in conditions.values())
                        if not has_external_id:
                            self.add_finding(
                                check_id="IAM-007", title=f"Role '{role['RoleName']}' trusts external account without ExternalId",
                                severity=Severity.CRITICAL, resource_type="AWS::IAM::Role",
                                resource_id=role["RoleName"], resource_arn=role.get("Arn", ""),
                                description=f"Trusts {p} without ExternalId condition (confused deputy risk).",
                                remediation="Add an ExternalId condition to the trust policy.",
                                details={"trusted_principal": p})

    def _check_wildcard_permissions(self, users, roles, policies):
        for user in users:
            for ip in user.get("UserPolicyList", []):
                doc = ip.get("PolicyDocument", {})
                if isinstance(doc, str): doc = json.loads(doc)
                for stmt in self._safe_stmts(doc):
                    if stmt.get("Effect") == "Allow":
                        res = stmt.get("Resource", [])
                        if isinstance(res, str): res = [res]
                        if "*" in res:
                            actions = stmt.get("Action", [])
                            if isinstance(actions, str): actions = [actions]
                            if "*" not in actions:
                                self.add_finding(
                                    check_id="IAM-008", title=f"User '{user['UserName']}' has wildcard resource permissions",
                                    severity=Severity.HIGH, resource_type="AWS::IAM::User",
                                    resource_id=user["UserName"],
                                    description=f"Actions {actions[:3]}... on Resource: *",
                                    remediation="Scope Resource to specific ARNs.")

    def _check_unused_users(self, cred_report):
        now = datetime.now(timezone.utc)
        for row in cred_report:
            user = row.get("user", "")
            if user == "<root_account>": continue
            last_login = row.get("password_last_used", "N/A")
            key1_used = row.get("access_key_1_last_used_date", "N/A")
            key2_used = row.get("access_key_2_last_used_date", "N/A")
            last_activity = None
            for dt_str in [last_login, key1_used, key2_used]:
                if dt_str not in ("N/A", "no_information", "not_supported", ""):
                    try:
                        dt = datetime.fromisoformat(dt_str.replace("+00:00", "+00:00"))
                        if not dt.tzinfo: dt = dt.replace(tzinfo=timezone.utc)
                        if last_activity is None or dt > last_activity:
                            last_activity = dt
                    except Exception:
                        pass
            if last_activity:
                days_inactive = (now - last_activity).days
                if days_inactive > 90:
                    self.add_finding(
                        check_id="IAM-009", title=f"User '{user}' inactive for {days_inactive} days",
                        severity=Severity.MEDIUM, resource_type="AWS::IAM::User",
                        resource_id=user, resource_arn=row.get("arn", ""),
                        description=f"No activity in {days_inactive} days. Consider removing.",
                        remediation="Disable or delete unused IAM users.")

    def _check_password_policy(self, policy, err):
        if err or not policy:
            self.add_finding(
                check_id="IAM-010", title="No custom password policy configured",
                severity=Severity.MEDIUM, resource_type="AWS::IAM::AccountPasswordPolicy",
                resource_id="password-policy",
                description="Account uses default password policy.",
                remediation="Configure a strong password policy with minimum length, complexity, and rotation.")
            return
        pp = policy.get("PasswordPolicy", policy)
        if pp.get("MinimumPasswordLength", 0) < 14:
            self.add_finding(
                check_id="IAM-011", title=f"Password minimum length is {pp.get('MinimumPasswordLength', 'unknown')}",
                severity=Severity.MEDIUM, resource_type="AWS::IAM::AccountPasswordPolicy",
                resource_id="password-policy",
                description="Minimum password length should be at least 14 characters.",
                remediation="Set MinimumPasswordLength to 14 or higher.")


    # ── Checks merged from awsperm ────────────────────────────────────────

    def _check_service_last_accessed(self, roles):
        """Flag roles that use a tiny fraction of their granted permissions."""
        iam = self.session.client("iam", region_name="us-east-1")
        # Sample top 10 roles by attached policy count to limit API calls
        sorted_roles = sorted(roles, key=lambda r: len(r.get("AttachedManagedPolicies", [])), reverse=True)[:10]
        for role in sorted_roles:
            arn = role.get("Arn", "")
            name = role.get("RoleName", "?")
            try:
                gen = iam.generate_service_last_accessed_details(Arn=arn)
                job_id = gen.get("JobId")
                if not job_id:
                    continue
                import time as _time
                for _ in range(8):
                    resp = iam.get_service_last_accessed_details(JobId=job_id)
                    if resp.get("JobStatus") == "COMPLETED":
                        services = resp.get("ServicesLastAccessed", [])
                        granted = len(services)
                        used = len([s for s in services if s.get("LastAuthenticated")])
                        if granted > 5 and used > 0:
                            ratio = used / granted * 100
                            if ratio < 25:
                                self.add_finding(
                                    check_id="IAM-012",
                                    title=f"Role '{name}' uses only {ratio:.0f}% of granted services ({used}/{granted})",
                                    severity=Severity.MEDIUM,
                                    resource_type="AWS::IAM::Role",
                                    resource_id=name, resource_arn=arn,
                                    description=f"Granted access to {granted} services but only used {used}. Over-permissioned.",
                                    remediation="Scope down the role's policies to only the services actually used.")
                        break
                    elif resp.get("JobStatus") == "FAILED":
                        break
                    _time.sleep(1)
            except Exception:
                pass

    def _check_access_analyzer(self):
        """Check IAM Access Analyzer for external access findings."""
        try:
            aa = self.session.client("accessanalyzer", region_name="us-east-1")
            analyzers_resp, err = safe_api_call(aa, "list_analyzers")
            if err:
                return
            analyzers = (analyzers_resp or {}).get("analyzers", [])
            if not analyzers:
                self.add_finding(
                    check_id="IAM-013",
                    title="IAM Access Analyzer is not enabled",
                    severity=Severity.MEDIUM,
                    resource_type="AWS::AccessAnalyzer::Analyzer",
                    resource_id="no-analyzer",
                    description="No Access Analyzer found. External access to resources is not being monitored.",
                    remediation="Enable IAM Access Analyzer to detect resources shared externally.")
                return
            total_findings = 0
            for analyzer in analyzers:
                try:
                    paginator = aa.get_paginator("list_findings")
                    for page in paginator.paginate(analyzerArn=analyzer["arn"],
                                                    filter={"status": {"eq": ["ACTIVE"]}}):
                        total_findings += len(page.get("findings", []))
                except Exception:
                    pass
            if total_findings > 0:
                self.add_finding(
                    check_id="IAM-014",
                    title=f"{total_findings} active Access Analyzer finding(s), external access detected",
                    severity=Severity.HIGH,
                    resource_type="AWS::AccessAnalyzer::Analyzer",
                    resource_id="access-analyzer-findings",
                    description=f"{total_findings} resources are accessible from outside your account.",
                    remediation="Review and remediate Access Analyzer findings in the IAM console.")
        except Exception:
            pass
