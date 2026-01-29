# Ropper Parameter Optimization

## Overview

- **Purpose**: Intelligently optimize Ropper ROP gadget finder parameters based on exploit type and architecture
- **Category**: tool-optimization
- **Severity**: high
- **Tags**: ropper, parameter-optimization, rop-gadgets, exploit-development

## Procedure / Knowledge Detail

### Gadget Type Selection

**ROP Gadgets**:
- Type: rop
- Purpose: Return-oriented programming

**JOP Gadgets**:
- Type: jop
- Purpose: Jump-oriented programming

### Quality Level Adjustment

**Quick Mode**:
- Quality: 1 (basic gadgets)

**Comprehensive Mode**:
- Quality: 3 (all gadgets)

### Implementation Code

```python
def _optimize_ropper_params(self, profile: TargetProfile, context: Dict[str, Any]) -> Dict[str, Any]:
    """Optimize Ropper parameters"""
    params = {"target": profile.target}

    if context.get("exploit_type") == "jop":
        params["gadget_type"] = "jop"
    else:
        params["gadget_type"] = "rop"

    if context.get("quick", False):
        params["quality"] = 1
    else:
        params["quality"] = 3

    return params
```

## Related Knowledge Items

- **tool_selection_strategy**: Selects ropper
- **attack_chain_generation_system**: Uses optimized parameters
- **parameter_optimization_system**: Framework for optimization

## Best Practices

1. Select gadget type based on exploit
2. Use quality level 1 for quick search
3. Use quality level 3 for comprehensive search
4. Filter gadgets by architecture
5. Combine gadgets for exploit chain
6. Test gadgets before deployment

## Notes

- Gadget finder for ROP/JOP exploits
- Supports multiple architectures
- Quality levels: 1-3
- Used in binary exploitation
