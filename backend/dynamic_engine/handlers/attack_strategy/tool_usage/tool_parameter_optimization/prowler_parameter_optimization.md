# Prowler Parameter Optimization

## Overview

- **Purpose**: Intelligently optimize Prowler AWS security assessment parameters based on cloud provider and region
- **Category**: tool-optimization
- **Severity**: high
- **Tags**: prowler, parameter-optimization, aws-security, cloud-assessment

## Procedure / Knowledge Detail

### Cloud Provider Selection

**AWS**:
- Provider: aws
- Profile: AWS credentials profile
- Region: AWS region (us-east-1, etc.)

### Profile and Region Configuration

**AWS Profile**: Named profile from ~/.aws/credentials
**AWS Region**: Target region for assessment

### Implementation Code

```python
def _optimize_prowler_params(self, profile: TargetProfile, context: Dict[str, Any]) -> Dict[str, Any]:
    """Optimize Prowler parameters"""
    params = {"target": profile.target}

    params["provider"] = "aws"
    params["profile"] = context.get("aws_profile", "default")
    params["region"] = context.get("aws_region", "us-east-1")
    params["output_format"] = "json"

    return params
```

## Related Knowledge Items

- **tool_selection_strategy**: Selects prowler
- **attack_chain_generation_system**: Uses optimized parameters
- **parameter_optimization_system**: Framework for optimization

## Best Practices

1. Specify AWS profile for authentication
2. Target specific regions for assessment
3. Use JSON output for automation
4. Review findings by severity
5. Remediate high-risk findings
6. Schedule regular assessments

## Notes

- AWS security assessment tool
- Checks AWS best practices
- Supports multiple regions
- Requires AWS credentials
