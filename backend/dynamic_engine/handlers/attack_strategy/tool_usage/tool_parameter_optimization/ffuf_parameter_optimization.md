# FFuf Parameter Optimization

## Overview

- **Purpose**: Intelligently optimize FFuf fuzzing tool parameters based on target type and stealth requirements
- **Category**: tool-optimization
- **Severity**: high
- **Tags**: ffuf, parameter-optimization, fuzzing, target-type-specific

## Procedure / Knowledge Detail

### Target Type-Specific Match Codes

**API_ENDPOINT**:
- Match codes: `200,201,202,204,301,302,401,403`
- Purpose: API-specific response codes

**Default (Web Application)**:
- Match codes: `200,204,301,302,307,401,403`
- Purpose: Common web response codes

### Context-Aware Thread Adjustment

**Stealth Mode**:
- Threads: `-t 10`
- Delay: `-p 1` (1 second between requests)
- Detection: Very low

**Aggressive Mode** (default):
- Threads: `-t 40`
- Detection: Higher

### Implementation Code

```python
def _optimize_ffuf_params(self, profile: TargetProfile, context: Dict[str, Any]) -> Dict[str, Any]:
    """Optimize FFuf parameters"""
    params = {"url": profile.target}

    if profile.target_type == TargetType.API_ENDPOINT:
        params["match_codes"] = "200,201,202,204,301,302,401,403"
    else:
        params["match_codes"] = "200,204,301,302,307,401,403"

    if context.get("stealth", False):
        params["additional_args"] = "-t 10 -p 1"
    else:
        params["additional_args"] = "-t 40"

    return params
```

## Related Knowledge Items

- **target_type_classification**: Determines target type
- **tool_selection_strategy**: Selects ffuf
- **attack_chain_generation_system**: Uses optimized parameters

## Best Practices

1. Use appropriate match codes for target type
2. Adjust threads based on target responsiveness
3. Use `-w` for wordlist specification
4. Use `-o` to save results
5. Use `-rate-limit` for rate-limited targets
6. Use `-timeout` for slow targets

## Notes

- Match codes: 200 (OK), 201 (Created), 204 (No Content), 301/302 (Redirect), 401/403 (Auth)
- Common wordlists: /usr/share/wordlists/
- Threads: 1-200 (default 40)
- Timeout: Default 10 seconds
