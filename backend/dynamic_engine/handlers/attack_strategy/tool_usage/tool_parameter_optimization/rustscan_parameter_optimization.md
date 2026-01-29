# Rustscan Parameter Optimization

## Overview

- **Purpose**: Intelligently optimize Rustscan fast port scanner parameters based on execution context
- **Category**: tool-optimization
- **Severity**: high
- **Tags**: rustscan, parameter-optimization, port-scanning, performance-tuning

## Procedure / Knowledge Detail

### Performance Tuning Modes

**Stealth Mode**:
- ulimit: 1000
- batch_size: 500
- timeout: 3000ms

**Aggressive Mode**:
- ulimit: 10000
- batch_size: 8000
- timeout: 800ms

**Normal Mode** (default):
- ulimit: 5000
- batch_size: 4500
- timeout: 1500ms

### Script Enablement

**Comprehensive Scans**:
- Enable scripts for detailed analysis
- Parameter: `scripts: True`

### Implementation Code

```python
def _optimize_rustscan_params(self, profile: TargetProfile, context: Dict[str, Any]) -> Dict[str, Any]:
    """Optimize Rustscan parameters"""
    params = {"target": profile.target}

    if context.get("stealth", False):
        params["ulimit"] = 1000
        params["batch_size"] = 500
        params["timeout"] = 3000
    elif context.get("aggressive", False):
        params["ulimit"] = 10000
        params["batch_size"] = 8000
        params["timeout"] = 800
    else:
        params["ulimit"] = 5000
        params["batch_size"] = 4500
        params["timeout"] = 1500

    if context.get("objective", "normal") == "comprehensive":
        params["scripts"] = True

    return params
```

## Related Knowledge Items

- **tool_selection_strategy**: Selects rustscan
- **attack_chain_generation_system**: Uses optimized parameters
- **parameter_optimization_system**: Framework for optimization

## Best Practices

1. Adjust ulimit based on system resources
2. Use scripts for comprehensive scans
3. Monitor for timeout errors
4. Use appropriate batch sizes
5. Test with small target first
6. Monitor system load

## Notes

- ulimit: File descriptor limit (1000-10000)
- batch_size: Ports per batch (500-8000)
- timeout: Milliseconds per port (800-3000)
- Fastest port scanner available
