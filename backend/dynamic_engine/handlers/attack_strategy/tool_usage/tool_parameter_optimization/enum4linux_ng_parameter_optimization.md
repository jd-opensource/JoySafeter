# Enum4linux-ng Parameter Optimization

## Overview

- **Purpose**: Intelligently optimize Enum4linux-ng SMB enumeration parameters with authentication support
- **Category**: tool-optimization
- **Severity**: high
- **Tags**: enum4linux-ng, parameter-optimization, smb-enumeration, windows-enumeration

## Procedure / Knowledge Detail

### Comprehensive Enumeration

**Default Configuration**:
- shares: True (enumerate shares)
- users: True (enumerate users)
- groups: True (enumerate groups)
- policy: True (enumerate policy)

### Authentication Support

**Username**: From context
- Parameter: `username: context["username"]`

**Password**: From context
- Parameter: `password: context["password"]`

**Domain**: From context
- Parameter: `domain: context["domain"]`

### Implementation Code

```python
def _optimize_enum4linux_ng_params(self, profile: TargetProfile, context: Dict[str, Any]) -> Dict[str, Any]:
    """Optimize Enum4linux-ng parameters"""
    params = {"target": profile.target}

    params["shares"] = True
    params["users"] = True
    params["groups"] = True
    params["policy"] = True

    if context.get("username"):
        params["username"] = context["username"]
    if context.get("password"):
        params["password"] = context["password"]
    if context.get("domain"):
        params["domain"] = context["domain"]

    return params
```

## Related Knowledge Items

- **target_analysis_workflow**: Provides target information
- **tool_selection_strategy**: Selects enum4linux-ng
- **attack_chain_generation_system**: Uses optimized parameters

## Best Practices

1. Enable comprehensive enumeration by default
2. Provide credentials when available
3. Specify domain for domain-joined systems
4. Use `-u` for username list
5. Use `-p` for password list
6. Save results with `-o` flag

## Notes

- Requires SMB access (port 445 or 139)
- Works on Windows and Samba systems
- Credentials improve enumeration results
- Domain information helps with enumeration
