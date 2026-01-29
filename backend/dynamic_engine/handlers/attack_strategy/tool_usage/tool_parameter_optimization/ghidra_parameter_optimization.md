# Ghidra Parameter Optimization

## Overview

- **Purpose**: Intelligently optimize Ghidra binary analysis parameters based on analysis scope
- **Category**: tool-optimization
- **Severity**: high
- **Tags**: ghidra, parameter-optimization, binary-analysis, reverse-engineering

## Procedure / Knowledge Detail

### Analysis Timeout Adjustment

**Quick Mode**:
- timeout: 120 seconds
- analysis_type: basic

**Comprehensive Mode**:
- timeout: 600 seconds
- analysis_type: advanced

### Project Configuration

**Project Name**: Generated from binary name
- Format: `ghidra_project_{binary_name}`

### Implementation Code

```python
def _optimize_ghidra_params(self, profile: TargetProfile, context: Dict[str, Any]) -> Dict[str, Any]:
    """Optimize Ghidra parameters"""
    params = {"target": profile.target}

    if context.get("quick", False):
        params["timeout"] = 120
        params["analysis_type"] = "basic"
    else:
        params["timeout"] = 600
        params["analysis_type"] = "advanced"

    binary_name = profile.target.split("/")[-1]
    params["project_name"] = f"ghidra_project_{binary_name}"

    return params
```

## Related Knowledge Items

- **tool_selection_strategy**: Selects ghidra
- **attack_chain_generation_system**: Uses optimized parameters
- **parameter_optimization_system**: Framework for optimization

## Best Practices

1. Use quick mode for initial analysis
2. Use comprehensive mode for detailed analysis
3. Adjust timeout based on binary size
4. Organize projects by binary name
5. Monitor analysis progress
6. Save analysis results

## Notes

- Requires Java runtime
- Analysis time depends on binary size
- Advanced analysis provides more details
- Project files can be reused
