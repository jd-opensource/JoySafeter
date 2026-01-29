# Basic Security Headers Check

## Overview

- Purpose: Perform fallback security headers validation to detect missing HTTP security headers when vulnerability scanners (nuclei, nikto) fail.
- Category: incident_response
- Severity: medium
- Tags: security-headers, fallback, vulnerability-scanning, incident-response

## Context and Use-Cases

- Graceful degradation when nuclei or nikto timeout or crash.
- Quick validation of critical security headers.
- Lightweight alternative for resource-constrained environments.

## Procedure / Knowledge detail

HTTP security header validation performs the following steps:

1. Accept target URL.
2. Send GET request with 10-second timeout.
3. Check for presence of critical security headers:
   - X-Frame-Options - Clickjacking protection
   - X-Content-Type-Options - MIME type sniffing protection
   - X-XSS-Protection - XSS protection
   - Strict-Transport-Security - HTTPS enforcement
   - Content-Security-Policy - Content Security Policy

4. For each missing header, create a vulnerability record with type, severity, description, and header name.
5. Return list of vulnerabilities or connection error if target unreachable.

## Examples

- Command:

  ```python
  vulns = degradation_manager._basic_security_check("https://example.com")
  # Returns: [
  #   {"type": "missing_security_header", "severity": "medium",
  #    "description": "Clickjacking protection missing", "header": "X-Frame-Options"},
  #   ...
  # ]
  ```

- Code Snippet:

  ```python
  security_headers = {
      "X-Frame-Options": "Clickjacking protection missing",
      "X-Content-Type-Options": "MIME type sniffing protection missing",
      "X-XSS-Protection": "XSS protection missing",
      "Strict-Transport-Security": "HTTPS enforcement missing",
      "Content-Security-Policy": "Content Security Policy missing"
  }

  for header, description in security_headers.items():
      if header not in headers:
          vulnerabilities.append({
              "type": "missing_security_header",
              "severity": "medium",
              "description": description,
              "header": header
          })
  ```

- Log Query/Rule:

  ```text
  "Basic security check" AND "missing_security_header" AND "degradation"
  ```
