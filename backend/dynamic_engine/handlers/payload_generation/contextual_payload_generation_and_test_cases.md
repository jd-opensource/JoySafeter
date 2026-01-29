# Contextual Payload Generation and Test Cases

## Overview
- Purpose: Generate payloads and test cases based on `attack_type`, `complexity`, and optional `technology` context.
- Category: web_security
- Severity: info
- Tags: automation, payload-generation, testing, web_security

## Context and Use-Cases
- Automates payload selection, URL-encoding variants, risk tagging, and creation of test cases.

## Key Parameters and Inputs
- attack_type (string, required): e.g., xss, sqli, lfi, cmd_injection, ssti, xxe
- complexity (string, optional): e.g., basic, advanced, bypass, time_based
- technology (string, optional): lowercase tech hint; not directly used in code shown

## Procedure
1. `_get_payloads(attack_type, complexity)` selects base payload list.
2. `_enhance_with_context` duplicates each payload and adds a URL-encoded variant; assigns `risk_level`.
3. `_generate_test_cases` builds up to 5 test cases with `method` and `expected_behavior`.

## Examples
- Example invocation structure:
```
{
  "attack_type": "xss",
  "complexity": "basic",
  "technology": ""
}
```
- Example generated test case (shape):
```
{
  "id": "test_1",
  "payload": "<script>alert('XSS')</script>",
  "method": "GET",
  "expected_behavior": "JavaScript execution or popup alert",
  "risk_level": "MEDIUM"
}
```

## Indicators / Detection
- Leverages expected behavior mapping for evaluation.

## Limitations and Caveats
- URL encoding only replaces spaces and angle brackets per code.
- Only first 5 payload variants become test cases.
