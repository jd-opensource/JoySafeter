# Security Policy

## Supported Versions

We release patches for security vulnerabilities. Which versions are eligible for receiving such patches depends on the severity of the vulnerability.

| Version | Supported          |
| ------- | ------------------ |
| 0.1.x   | :white_check_mark: |

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
- **Strong secrets**: Generate cryptographically secure keys for `SECRET_KEY` and `CREDENTIAL_ENCRYPTION_KEY`
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
