# Risk Assessment Keywords

## Overview
- Purpose: Describe the simple keyword-based risk classification used for payloads.
- Category: web_security
- Severity: info
- Tags: risk, classification, heuristics, web_security

## Context and Use-Cases
- Categorize payloads as HIGH, MEDIUM, or LOW risk via substring checks.

## Key Parameters and Inputs
- Input: payload string

## Procedure
1. Lowercase the payload.
2. If any of [system, exec, eval, cmd, shell, passwd, etc] present => HIGH.
3. Else if any of [script, alert, union, select] present => MEDIUM.
4. Else => LOW.

## Examples
- Pseudocode:
```
if any(h in payload for h in ["system","exec","eval","cmd","shell","passwd","etc"]):
  return HIGH
elif any(m in payload for m in ["script","alert","union","select"]):
  return MEDIUM
else:
  return LOW
```

## Limitations and Caveats
- Keyword-only heuristic; no parsing or context awareness.

## Source Excerpts
- [S1] high_risk_indicators = ["system", "exec", "eval", "cmd", "shell", "passwd", "etc"]

## References
-
