# Angr Parameter Optimization

## Overview

- **Purpose**: Intelligently optimize Angr symbolic execution parameters based on analysis type
- **Category**: tool-optimization
- **Severity**: high
- **Tags**: angr, parameter-optimization, symbolic-execution, binary-analysis

## Procedure / Knowledge Detail

### Analysis Type Selection

**Symbolic Execution**:
- Type: symbolic
- Purpose: Dynamic symbolic execution

**Control Flow Graph**:
- Type: cfg
- Purpose: Static analysis

**Static Analysis**:
- Type: static
- Purpose: Quick static analysis

### Find/Avoid Address Configuration

**Find Addresses**: Target addresses to reach
**Avoid Addresses**: Addresses to avoid

### Implementation Code

```python
def _optimize_angr_params(self, profile: TargetProfile, context: Dict[str, Any]) -> Dict[str, Any]:
    """Optimize Angr parameters"""
    params = {"target": profile.target}

    if context.get("analysis_type") == "cfg":
        params["analysis_type"] = "cfg"
    elif context.get("analysis_type") == "static":
        params["analysis_type"] = "static"
    else:
        params["analysis_type"] = "symbolic"

    params["find_addresses"] = context.get("find_addresses", [])
    params["avoid_addresses"] = context.get("avoid_addresses", [])

    return params
```

## Related Knowledge Items

- **tool_selection_strategy**: Selects angr
- **attack_chain_generation_system**: Uses optimized parameters
- **parameter_optimization_system**: Framework for optimization

## Best Practices

1. Select analysis type based on goal
2. Use symbolic execution for path finding
3. Use CFG for control flow analysis
4. Specify find/avoid addresses
5. Monitor memory usage
6. Set appropriate timeouts

## Notes

- Symbolic execution engine
- Supports multiple architectures
- Memory intensive
- Used in binary analysis and CTF
