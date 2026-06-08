# Troubleshooting — Kulshan CLI

## No AWS credentials configured

```
botocore.exceptions.NoCredentialsError: Unable to locate credentials
```

- Run `aws configure` to set up a default profile
- Or export environment variables: `AWS_ACCESS_KEY_ID` and `AWS_SECRET_ACCESS_KEY`
- Or use AWS SSO: `aws sso login --profile your-profile`

## Expired credentials / expired SSO session

```
botocore.exceptions.ClientError: ExpiredToken
```

- Re-authenticate with `aws sso login --profile your-profile`
- For IAM users, rotate or refresh your access keys via `aws configure`
- For assumed roles, re-run `aws sts assume-role` or your wrapper script

## Permission denied (AccessDenied)

```
botocore.exceptions.ClientError: An error occurred (AccessDenied) when calling the DescribeInstances operation
```

- Attach the Kulshan IAM policy from `kulshan/iam/kulshan-readonly.json` to your user or role
- Alternatively, attach the AWS managed policies `ViewOnlyAccess` + `SecurityAudit`
- Some packs will gracefully skip checks they lack permissions for — look for `[SKIPPED]` in output

## Cost Explorer not enabled

```
Cost Explorer has not been enabled for this account
```

- Enable Cost Explorer in the AWS Console: **Billing → Cost Explorer → Enable**
- Data takes up to 24 hours to populate after enabling
- The `cost` pack will report 0 findings until data is available — this is expected

## Wrong region / no resources found

```
0 findings across all packs
```

- Kulshan auto-discovers enabled regions by default
- Use `--quick` to limit scanning to 3 regions for faster iteration
- Regions with no resources are handled gracefully — 0 findings is not an error

## Role assumption failures (`--role-arn`)

```
botocore.exceptions.ClientError: An error occurred (AccessDenied) when calling the AssumeRole operation
```

- Ensure your calling identity has `sts:AssumeRole` permission for the target role ARN
- Ensure the target role's trust policy allows your identity as a principal
- Verify the role ARN is correct: `aws sts assume-role --role-arn <arn> --role-session-name test`

## Python version too old

```
SyntaxError: invalid syntax
```

- Kulshan requires Python 3.9+
- Check your version: `python --version`
- Use `pyenv` or your system package manager to install a supported version

## Import errors after install

```
ModuleNotFoundError: No module named 'Kulshan.packs.cost'
```

- Install with all optional dependencies: `pip install -e "Kulshan[all]"`
- Or install core only: `pip install -e kulshan`
- If using a virtual environment, make sure it's activated before running `Kulshan`
