# Masscan Parameter Optimization

## Overview

- **Purpose**: Intelligently optimize Masscan ultra-fast port scanner parameters with intelligent rate limiting
- **Category**: tool-optimization
- **Severity**: high
- **Tags**: masscan, parameter-optimization, port-scanning, rate-limiting

## Procedure / Knowledge Detail

### Intelligent Rate Limiting

**Stealth Mode**: 100 packets/sec
- Detection: Very low
- Speed: Slow

**Aggressive Mode**: 10000 packets/sec
- Detection: High
- Speed: Very fast

**Normal Mode** (default): 1000 packets/sec
- Detection: Medium
- Speed: Fast

### Banner Grabbing

**Service Detection**: Enable banners
- Parameter: `banners: True`
- Purpose: Identify services on open ports

### Implementation Code

```python
def _optimize_masscan_params(self, profile: TargetProfile, context: Dict[str, Any]) -> Dict[str, Any]:
    """Optimize Masscan parameters"""
    params = {"target": profile.target}

    if context.get("stealth", False):
        params["rate"] = 100
    elif context.get("aggressive", False):
        params["rate"] = 10000
    else:
        params["rate"] = 1000

    if context.get("service_detection", True):
        params["banners"] = True

    return params
```

## Related Knowledge Items

- **tool_selection_strategy**: Selects masscan
- **attack_chain_generation_system**: Uses optimized parameters
- **parameter_optimization_system**: Framework for optimization

## Best Practices

1. Adjust rate based on network capacity
2. Enable banners for service detection
3. Use appropriate rate for stealth
4. Monitor network impact
5. Test with small target first
6. Use `-p` for specific ports

## Notes

- Rate: Packets per second (100-10000)
- Fastest port scanner available
- Requires root/admin privileges
- Good for large-scale scanning
