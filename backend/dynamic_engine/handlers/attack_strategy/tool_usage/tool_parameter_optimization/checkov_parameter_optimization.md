# Checkov Parameter Optimization

## Overview

- **Purpose**: Intelligently optimize Checkov Infrastructure-as-Code security scanner parameters
- **Category**: tool-optimization
- **Severity**: high
- **Tags**: checkov, parameter-optimization, iac-security, infrastructure-scanning

## Procedure / Knowledge Detail

### Framework Auto-Detection

**Terraform**:
- Framework: terraform
- Purpose: Terraform IaC scanning

**Kubernetes**:
- Framework: kubernetes
- Purpose: Kubernetes manifest scanning

### Directory Scanning

**Target Directory**: IaC files directory

### Implementation Code

```python
def _optimize_checkov_params(self, profile: TargetProfile, context: Dict[str, Any]) -> Dict[str, Any]:
    """Optimize Checkov parameters"""
    params = {"target": profile.target}

    params["framework"] = context.get("framework", "auto")
    params["directory"] = profile.target
    params["output_format"] = "json"

    return params
```

## Related Knowledge Items

- **tool_selection_strategy**: Selects checkov
- **attack_chain_generation_system**: Uses optimized parameters
- **parameter_optimization_system**: Framework for optimization

## Best Practices

1. Specify framework when known
2. Scan entire IaC directory
3. Use JSON output for automation
4. Review findings by severity
5. Remediate misconfigurations
6. Integrate into CI/CD pipeline

## Notes

- Infrastructure-as-Code security scanner
- Supports Terraform, Kubernetes, CloudFormation
- Detects misconfigurations
- Can be integrated into CI/CD
