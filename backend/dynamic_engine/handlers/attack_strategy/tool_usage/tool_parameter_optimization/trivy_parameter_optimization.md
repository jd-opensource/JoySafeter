# Trivy Parameter Optimization

## Overview

- **Purpose**: Intelligently optimize Trivy vulnerability scanner parameters based on scan type
- **Category**: tool-optimization
- **Severity**: high
- **Tags**: trivy, parameter-optimization, vulnerability-scanning, container-security

## Procedure / Knowledge Detail

### Scan Type Detection

**Image Scanning**:
- Type: image
- Target: Container image

**Filesystem Scanning**:
- Type: fs
- Target: Filesystem directory

### Severity Filtering

**High and Critical**:
- Severity: HIGH,CRITICAL
- Purpose: Focus on critical vulnerabilities

### Implementation Code

```python
def _optimize_trivy_params(self, profile: TargetProfile, context: Dict[str, Any]) -> Dict[str, Any]:
    """Optimize Trivy parameters"""
    params = {"target": profile.target}

    if context.get("scan_type") == "fs":
        params["scan_type"] = "fs"
    else:
        params["scan_type"] = "image"

    params["severity"] = context.get("severity", "HIGH,CRITICAL")
    params["output_format"] = "json"

    return params
```

## Related Knowledge Items

- **tool_selection_strategy**: Selects trivy
- **attack_chain_generation_system**: Uses optimized parameters
- **parameter_optimization_system**: Framework for optimization

## Best Practices

1. Select scan type based on target
2. Filter by severity level
3. Use JSON output for automation
4. Review findings regularly
5. Remediate vulnerabilities
6. Schedule periodic scans

## Notes

- Container vulnerability scanner
- Supports image and filesystem scanning
- Fast and accurate
- Supports multiple registries
