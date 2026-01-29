# AutoRecon Parameter Optimization

## Overview

- **Purpose**: Intelligently optimize AutoRecon automated reconnaissance parameters based on scan depth
- **Category**: tool-optimization
- **Severity**: high
- **Tags**: autorecon, parameter-optimization, reconnaissance, automated-scanning

## Procedure / Knowledge Detail

### Scan Depth Adjustment

**Quick Mode**:
- port_scans: top-100-ports
- timeout: 180 seconds

**Comprehensive Mode** (default):
- port_scans: top-1000-ports
- timeout: 600 seconds

### Output Directory

**Configuration**:
- Format: `/tmp/autorecon_{target_with_underscores}`
- Purpose: Organize results by target

### Implementation Code

```python
def _optimize_autorecon_params(self, profile: TargetProfile, context: Dict[str, Any]) -> Dict[str, Any]:
    """Optimize AutoRecon parameters"""
    params = {"target": profile.target}

    if context.get("quick", False):
        params["port_scans"] = "top-100-ports"
        params["timeout"] = 180
    elif context.get("comprehensive", True):
        params["port_scans"] = "top-1000-ports"
        params["timeout"] = 600

    params["output_dir"] = f"/tmp/autorecon_{profile.target.replace('.', '_')}"
    return params
```

## Related Knowledge Items

- **tool_selection_strategy**: Selects autorecon
- **attack_chain_generation_system**: Uses optimized parameters
- **parameter_optimization_system**: Framework for optimization

## Best Practices

1. Use quick mode for time-constrained assessments
2. Use comprehensive mode for thorough reconnaissance
3. Monitor output directory for results
4. Adjust timeout based on network conditions
5. Review results regularly during scan
6. Save results for later analysis

## Notes

- Combines multiple reconnaissance tools
- Automated workflow for efficiency
- Requires significant time for comprehensive scans
- Generates detailed reports
