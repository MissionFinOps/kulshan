"""STS verification for workspace connections.

Verifies AWS credentials by calling sts:GetCallerIdentity after
optional role assumption. Never stores credentials, tokens, or
SSO cache contents.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class StsVerificationResult:
    """Result of STS credential verification."""

    account_id: str
    arn: str
    user_id: str


class StsVerificationError(Exception):
    """STS verification failed."""

    def __init__(self, message: str, cause: Exception | None = None):
        self.cause = cause
        super().__init__(message)


def verify_credentials(
    profile: str,
    role_arn: str | None = None,
    credential_account: str | None = None,
) -> StsVerificationResult:
    """
    Verify AWS credentials via STS GetCallerIdentity.

    Flow:
    1. Create boto3 session using the supplied profile.
    2. If role_arn is provided, assume the role first.
    3. Call sts:GetCallerIdentity on the final credentials.
    4. If credential_account is provided, assert it matches.

    Args:
        profile: AWS CLI profile name.
        role_arn: Optional IAM role ARN to assume.
        credential_account: Optional 12-digit account assertion.

    Returns:
        StsVerificationResult with the verified identity.

    Raises:
        StsVerificationError: On any failure (unknown profile,
            expired SSO, permission denied, role assumption failure,
            credential account mismatch).
    """
    import boto3
    from botocore.exceptions import (
        BotoCoreError,
        ClientError,
        NoCredentialsError,
        ProfileNotFound,
    )

    # Step 1: Create session from profile
    try:
        session = boto3.Session(profile_name=profile)
    except ProfileNotFound as e:
        raise StsVerificationError(
            f"AWS profile '{profile}' not found. "
            "Check your ~/.aws/config or AWS SSO configuration.",
            cause=e,
        ) from e
    except (BotoCoreError, Exception) as e:
        raise StsVerificationError(
            f"Cannot create AWS session with profile '{profile}': {e}",
            cause=e,
        ) from e

    # Step 2: Assume role if configured
    if role_arn:
        try:
            sts_client = session.client("sts")
            response = sts_client.assume_role(
                RoleArn=role_arn,
                RoleSessionName="kulshan-workspace-verify",
            )
            creds = response["Credentials"]
            session = boto3.Session(
                aws_access_key_id=creds["AccessKeyId"],
                aws_secret_access_key=creds["SecretAccessKey"],
                aws_session_token=creds["SessionToken"],
            )
        except ClientError as e:
            error_code = e.response.get("Error", {}).get("Code", "")
            if error_code == "AccessDenied":
                raise StsVerificationError(
                    f"Permission denied when assuming role. "
                    f"Verify the trust policy allows the source profile.",
                    cause=e,
                ) from e
            raise StsVerificationError(
                f"Role assumption failed: {e}",
                cause=e,
            ) from e
        except NoCredentialsError as e:
            raise StsVerificationError(
                f"No valid credentials for profile '{profile}'. "
                "SSO session may be expired. Run: aws sso login --profile "
                f"{profile}",
                cause=e,
            ) from e
        except (BotoCoreError, Exception) as e:
            raise StsVerificationError(
                f"Role assumption failed: {e}",
                cause=e,
            ) from e

    # Step 3: GetCallerIdentity on final credentials
    try:
        sts_client = session.client("sts")
        identity = sts_client.get_caller_identity()
    except NoCredentialsError as e:
        raise StsVerificationError(
            f"No valid credentials for profile '{profile}'. "
            "SSO session may be expired. Run: aws sso login --profile "
            f"{profile}",
            cause=e,
        ) from e
    except ClientError as e:
        raise StsVerificationError(
            f"STS GetCallerIdentity failed: {e}",
            cause=e,
        ) from e
    except (BotoCoreError, Exception) as e:
        raise StsVerificationError(
            f"STS verification failed: {e}",
            cause=e,
        ) from e

    result = StsVerificationResult(
        account_id=identity["Account"],
        arn=identity["Arn"],
        user_id=identity["UserId"],
    )

    # Step 4: Assert credential account if supplied
    if credential_account and result.account_id != credential_account:
        raise StsVerificationError(
            f"Credential account mismatch: expected {credential_account}, "
            f"but STS returned {result.account_id}. "
            "Verify the profile and role configuration.",
        )

    return result
