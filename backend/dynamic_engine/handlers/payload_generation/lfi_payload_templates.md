# LFI Payload Templates

## Overview
- Purpose: Provide reusable Local File Inclusion payloads for traversal and file disclosure testing.
- Category: web_security
- Severity: info
- Tags: lfi, payloads, web_security, path-traversal

## Context and Use-Cases
- Testing file inclusion parameters for traversal and sensitive file access.

## Key Parameters and Inputs
- attack_type (string): "lfi"
- complexity (string): one of [basic, advanced]

## Procedure
1. Try straightforward traversal to known sensitive files.
2. Use encoded or alternate path separator variants.

## Examples
- Payloads:
```
../../../etc/passwd
..%2F..%2F..%2Fetc%2Fpasswd
/var/log/apache2/access.log
```

## Indicators / Detection
- Patterns: many `../`, `%2F` encodings, references to `/etc/passwd`, `windows\\system32`.

## Limitations and Caveats
- Risk classification is keyword-based.

-
