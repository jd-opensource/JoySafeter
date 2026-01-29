# Arjun Parameter Optimization

## Overview

- **Purpose**: Intelligently optimize Arjun API parameter discovery parameters based on target endpoint and scanning scope
- **Category**: tool-optimization
- **Severity**: high
- **Tags**: arjun, parameter-optimization, api-testing, parameter-discovery, api-endpoint

## Procedure / Knowledge Detail

### Target Endpoint Configuration

**Target URL**: API endpoint to discover parameters
**HTTP Method**: GET, POST, PUT, DELETE, etc.

### Wordlist Selection

**Default Wordlist**: Common API parameters
**Custom Wordlist**: User-provided parameter list

### Threading Optimization

**Quick Mode**:
- threads: 10
- timeout: 5 seconds

**Comprehensive Mode**:
- threads: 50
- timeout: 10 seconds

### Implementation Code

```python
def _optimize_arjun_params(self, profile: TargetProfile, context: Dict[str, Any]) -> Dict[str, Any]:
    """Optimize Arjun parameters"""
    params = {"target": profile.target}

    params["url"] = profile.target
    params["method"] = context.get("http_method", "GET")
    params["wordlist"] = context.get("wordlist", "default")

    if context.get("quick", False):
        params["threads"] = 10
        params["timeout"] = 5
    else:
        params["threads"] = 50
        params["timeout"] = 10

    return params
```

## Related Knowledge Items

- **tool_selection_strategy**: Selects arjun
- **attack_chain_generation_system**: Uses optimized parameters
- **parameter_optimization_system**: Framework for optimization

## Best Practices

1. Specify target endpoint correctly
2. Use appropriate wordlist for API type
3. Adjust threads based on target capacity
4. Monitor for rate limiting
5. Verify discovered parameters
6. Document API parameters found

## Notes

- API parameter discovery tool
- Discovers hidden API parameters
- Supports multiple HTTP methods
- Wordlist-based discovery
- Useful for API reconnaissance
