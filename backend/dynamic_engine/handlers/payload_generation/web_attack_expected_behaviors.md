# Web Attack Expected Behaviors

## Overview
- Purpose: Document expected application behaviors per attack type used when forming test cases.
- Category: web_security
- Severity: info
- Tags: expected-behavior, testing, web_security

## Context and Use-Cases
- Helps evaluate whether a test case succeeded by comparing actual vs expected behavior.

## Key Parameters and Inputs
- attack_type: one of [xss, sqli, lfi, cmd_injection, ssti, xxe]

## Procedure
- Expected behaviors:
  - xss: JavaScript execution or popup alert
  - sqli: Database error or data extraction
  - lfi: File content disclosure
  - cmd_injection: Command execution on server
  - ssti: Template expression evaluation
  - xxe: XML external entity processing

## Examples
- Usage: Set `expected_behavior` for each test case using this mapping.

## Limitations and Caveats
- High-level descriptions; not exhaustive.

## Source Excerpts
- [S1] behaviors = {"xss": "JavaScript execution or popup alert", "sqli": "Database error or data extraction", ...}

## References
-
