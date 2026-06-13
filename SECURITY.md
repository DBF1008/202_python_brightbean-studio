# Security Policy

## Supported Versions

| Version | Supported |
|---------|-----------|
| Latest on `main` | Yes |

## Reporting a Vulnerability

If you discover a security vulnerability in Brightbean, please report it responsibly.

**Do not open a public GitHub issue for security vulnerabilities.**

Instead, please email **security@brightbean.xyz** with:

- A description of the vulnerability
- Steps to reproduce
- The potential impact
- Any suggested fix (optional)

### What to expect

- **Acknowledgment** within 48 hours
- **Status update** within 7 days with an assessment and expected timeline
- **Fix and disclosure** coordinated with you before any public announcement

## Scope

The following are in scope for security reports:

- Authentication and authorization bypasses
- SQL injection, XSS, CSRF, or other injection attacks
- Credential or secret exposure
- Privilege escalation
- Data leakage between organizations or workspaces

The following are **out of scope**:

- Vulnerabilities in third-party dependencies (report these upstream, but let us know so we can update)
- Social engineering attacks
- Denial of service attacks
- Issues requiring physical access to a server

## Security Best Practices for Self-Hosters

- Always change `SECRET_KEY` and `ENCRYPTION_KEY_SALT` from the defaults before deploying
- Run with `DEBUG=false` in production
- Use HTTPS (the Docker Compose production setup includes Caddy for auto-HTTPS)
- Keep your instance updated with the latest version
- Use strong passwords for your PostgreSQL database
- Restrict database access to the application server only
