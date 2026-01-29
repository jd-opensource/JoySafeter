# Kube-Hunter Parameter Optimization

## Overview

- **Purpose**: Intelligently optimize Kube-Hunter Kubernetes security assessment parameters
- **Category**: tool-optimization
- **Severity**: high
- **Tags**: kube-hunter, parameter-optimization, kubernetes-security, container-security

## Procedure / Knowledge Detail

### Kubernetes Target Specification

**Target Type**: Kubernetes cluster endpoint

### CIDR and Interface Configuration

**CIDR Range**: Network range to scan
**Interface**: Network interface for scanning

### Active Hunting Mode

**Enable Active Hunting**: Aggressive vulnerability testing

### Implementation Code

```python
def _optimize_kube_hunter_params(self, profile: TargetProfile, context: Dict[str, Any]) -> Dict[str, Any]:
    """Optimize Kube-Hunter parameters"""
    params = {"target": profile.target}

    params["cidr"] = context.get("cidr", "10.0.0.0/8")
    params["interface"] = context.get("interface", "eth0")
    params["active"] = context.get("active_hunting", False)

    return params
```

## Related Knowledge Items

- **tool_selection_strategy**: Selects kube-hunter
- **attack_chain_generation_system**: Uses optimized parameters
- **parameter_optimization_system**: Framework for optimization

## Best Practices

1. Specify Kubernetes cluster endpoint
2. Configure CIDR range appropriately
3. Select correct network interface
4. Use active hunting carefully
5. Review findings by severity
6. Remediate vulnerabilities

## Notes

- Kubernetes security scanner
- Hunts for security vulnerabilities
- Supports active and passive modes
- Requires Kubernetes access
