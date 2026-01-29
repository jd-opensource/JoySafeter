# Pwntools Parameter Optimization

## Overview

- **Purpose**: Intelligently optimize Pwntools exploit development parameters based on exploit type
- **Category**: tool-optimization
- **Severity**: high
- **Tags**: pwntools, parameter-optimization, exploit-development, pwn-tools

## Procedure / Knowledge Detail

### Exploit Type Selection

**Local Exploit**:
- Type: local
- Target: Binary file path

**Remote Exploit**:
- Type: remote
- Host: Remote target IP/hostname
- Port: Remote target port

### Implementation Code

```python
def _optimize_pwntools_params(self, profile: TargetProfile, context: Dict[str, Any]) -> Dict[str, Any]:
    """Optimize Pwntools parameters"""
    params = {"target": profile.target}

    if profile.target_type == TargetType.BINARY_FILE:
        params["exploit_type"] = "local"
        params["binary"] = profile.target
    else:
        params["exploit_type"] = "remote"
        params["host"] = profile.target
        params["port"] = context.get("port", 9999)

    return params
```

## Related Knowledge Items

- **tool_selection_strategy**: Selects pwntools
- **attack_chain_generation_system**: Uses optimized parameters
- **parameter_optimization_system**: Framework for optimization

## Best Practices

1. Specify exploit type correctly
2. Provide binary path for local exploits
3. Provide host/port for remote exploits
4. Use appropriate payload encoding
5. Test exploits in safe environment
6. Document exploit parameters

## Notes

- Python library for exploit development
- Supports multiple architectures
- Requires binary analysis knowledge
- Common in CTF competitions
