# Scout Suite Parameter Optimization

## Overview

- **Purpose**: Intelligently optimize Scout Suite multi-cloud assessment parameters
- **Category**: tool-optimization
- **Severity**: high
- **Tags**: scout-suite, parameter-optimization, multi-cloud, cloud-assessment

## Procedure / Knowledge Detail

### Multi-Cloud Provider Support

**AWS**:
- Provider: aws
- Profile: AWS credentials profile

**Azure**:
- Provider: azure
- Credentials: Azure service principal

**GCP**:
- Provider: gcp
- Credentials: GCP service account

### Report Directory Configuration

**Output Directory**: Report storage location

### Implementation Code

```python
def _optimize_scout_suite_params(self, profile: TargetProfile, context: Dict[str, Any]) -> Dict[str, Any]:
    """Optimize Scout Suite parameters"""
    params = {"target": profile.target}

    params["provider"] = context.get("cloud_provider", "aws")
    params["profile"] = context.get("profile", "default")
    params["report_dir"] = context.get("report_dir", "/tmp/scout-suite-report")

    return params
```

## Related Knowledge Items

- **tool_selection_strategy**: Selects scout-suite
- **attack_chain_generation_system**: Uses optimized parameters
- **parameter_optimization_system**: Framework for optimization

## Best Practices

1. Specify cloud provider
2. Provide credentials/profile
3. Configure report directory
4. Review findings by severity
5. Track remediation progress
6. Schedule regular assessments

## Notes

- Multi-cloud security assessment
- Supports AWS, Azure, GCP
- Generates HTML reports
- Requires cloud credentials
