# Security Policy

## Supported Versions

| Version | Supported |
|---------|-----------|
| 0.1.x   | Yes       |

## Reporting a Vulnerability

If you discover a security vulnerability in Kulshan, please report it
responsibly.

**Do not open a public GitHub issue for security vulnerabilities.**

Instead, please email: security@missionfinops.com

Include:
- A description of the vulnerability
- Steps to reproduce
- Potential impact
- Suggested fix (if you have one)

## Response Timeline

- Acknowledgment: within 48 hours
- Initial assessment: within 5 business days
- Fix timeline: depends on severity, typically within 30 days

## Scope

Kulshan is a read-only tool. It never writes to your AWS account.
The IAM policies we provide contain only read actions (Describe, Get,
List). If you find a code path that could trigger a write API call,
that is a critical security issue and should be reported immediately.

## Security Design Principles

1. **Read-only AWS access**: No write, create, delete, or modify API calls
2. **Local-only AI**: SLM inference runs on your machine, never in the cloud
3. **Opt-in telemetry**: Anonymous usage metrics are disabled by default
4. **Offline license validation**: JWT verification uses a bundled public key
5. **No credential storage**: Kulshan uses your existing AWS credential chain
