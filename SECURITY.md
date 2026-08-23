# Security Policy

## Supported Versions

We release patches for security vulnerabilities. Which versions are eligible for receiving such patches depends on the severity of the vulnerability.

| Version | Supported          |
| ------- | ------------------ |
| 0.3.x   | :white_check_mark: |
| 0.2.x   | Critical fixes only |
| 0.1.x   | :x: |

## Reporting a Vulnerability

We take the security of JoySafeter seriously. If you believe you have found a security vulnerability, please report it to us as described below.

**Please do not report security vulnerabilities through public GitHub issues.**

### How to Report

1. **Email**: Send a detailed report to security@joysafeter.ai (or create a private security advisory on GitHub)
2. **Include**:
   - Type of vulnerability (e.g., SQL injection, XSS, authentication bypass)
   - Full paths of source file(s) related to the vulnerability
   - Step-by-step instructions to reproduce the issue
   - Proof-of-concept or exploit code (if possible)
   - Impact of the vulnerability

### What to Expect

- **Acknowledgment**: We will acknowledge receipt of your vulnerability report within 48 hours
- **Communication**: We will keep you informed of the progress towards a fix and full announcement
- **Resolution**: We aim to resolve critical vulnerabilities within 7 days
- **Credit**: We will credit you in the security advisory (unless you prefer to remain anonymous)

## Security Best Practices

When deploying JoySafeter, please ensure:

### Environment Configuration

- **Never commit secrets**: Use environment variables for all sensitive configuration
- **Strong secrets**: Generate cryptographically secure keys for `SECRET_KEY`, `JOYSAFETER_VAULT_ENCRYPTION_KEY`, and every entry in `JOYSAFETER_CREDENTIAL_ENCRYPTION_KEYRING`.
- **Safe key rotation**: Never replace `JOYSAFETER_VAULT_ENCRYPTION_KEY` in place. Add the new key to the keyring, initialize its database canary with `backend/scripts/credential_encryption_rotation.py --initialize-missing-canaries`, switch `JOYSAFETER_CREDENTIAL_ENCRYPTION_WRITE_KEY_ID`, rewrap all persisted material, and retain old read keys through the rollback window. Canary initialization is concurrency-safe: the first committed row wins, conflicting initializers never overwrite it, and every caller validates the persisted winner inside an atomic savepoint. The v2 envelope authenticates the exact `enc:v2:<key_id>:` prefix as AES-GCM associated data; key-ID relabeling, malformed credential JSON, and plaintext encountered by online rewrap all fail closed. API, worker, and orchestrator startup also reject removal of any key still referenced by persisted material.
- **Offline ciphertext verification**: Startup inventory intentionally checks envelope shape and read-key coverage without decrypting every business value. Run `backend/.venv/bin/python backend/scripts/credential_encryption_rotation.py --verify-integrity` before retiring read keys and as a periodic control. The verifier uses a repeatable-read, database-enforced read-only transaction; pages through Credential data, OAuth secret fields, Task Identity material, and Repository Tokens; decrypts every non-empty value; exits non-zero on any issue; and reports only surface, record ID, field, and a stable error category.
- **HTTPS only**: Always use HTTPS in production
- **Cookie security**: Enable `COOKIE_SECURE=true` in production

### Database Security

- **Strong passwords**: Use complex passwords for database users
- **Network isolation**: Keep databases in private networks
- **Encryption**: Enable encryption at rest and in transit

### API Security

- **Rate limiting**: Configure appropriate rate limits
- **CORS**: Restrict CORS origins to trusted domains only
- **Authentication**: Never disable authentication in production

### Docker Security

- **Non-root users**: Run containers as non-root users
- **Read-only filesystem**: Use read-only filesystem where possible
- **Resource limits**: Set CPU and memory limits

## Known Security Considerations

1. **MCP Tool Execution**: MCP tools can execute arbitrary code. Only enable trusted MCP servers.
2. **Agent Sandbox**: Agents may interact with external systems. Use appropriate isolation.
3. **File Uploads**: Validate and sanitize all file uploads.

## Security Updates

Security updates are released as patch versions and announced through:

- GitHub Security Advisories
- Release notes
- Project mailing list (if configured)

We recommend always running the latest stable version.
