# Nuclei Parameter Optimization

## Overview

- **Purpose**: Intelligently optimize Nuclei vulnerability scanner parameters based on execution context and detected technologies
- **Category**: tool-optimization
- **Severity**: high
- **Tags**: nuclei, parameter-optimization, vulnerability-scanning, technology-specific

## Context and Use-Cases

Nuclei parameter optimization is essential for:

- **Severity Filtering**: Focus on critical/high vulnerabilities
- **Technology-Specific Tags**: Target known CMS vulnerabilities
- **Quick vs Comprehensive**: Balance speed vs coverage
- **Template Selection**: Choose appropriate vulnerability templates

## Procedure / Knowledge Detail

### Severity-Based Filtering

**Quick Mode** (`context.get("quick", False)`):
- Severity: `critical,high`
- Purpose: Fast vulnerability scan
- Coverage: High-impact vulnerabilities only

**Comprehensive Mode** (default):
- Severity: `critical,high,medium`
- Purpose: Thorough vulnerability assessment
- Coverage: All severity levels

### Technology-Specific Tags

**WordPress Detection**:
- Tag: `wordpress`
- Purpose: WordPress-specific vulnerabilities

**Drupal Detection**:
- Tag: `drupal`
- Purpose: Drupal-specific vulnerabilities

**Joomla Detection**:
- Tag: `joomla`
- Purpose: Joomla-specific vulnerabilities

### Implementation Code

```python
def _optimize_nuclei_params(self, profile: TargetProfile, context: Dict[str, Any]) -> Dict[str, Any]:
    """Optimize Nuclei parameters"""
    params = {"target": profile.target}

    # Severity filtering
    if context.get("quick", False):
        params["severity"] = "critical,high"
    else:
        params["severity"] = "critical,high,medium"

    # Technology-specific tags
    tags = []
    for tech in profile.technologies:
        if tech == TechnologyStack.WORDPRESS:
            tags.append("wordpress")
        elif tech == TechnologyStack.DRUPAL:
            tags.append("drupal")
        elif tech == TechnologyStack.JOOMLA:
            tags.append("joomla")

    if tags:
        params["tags"] = ",".join(tags)

    return params
```

## Related Knowledge Items

- **cms_detection_system**: Detects CMS types
- **tool_selection_strategy**: Selects nuclei
- **attack_chain_generation_system**: Uses optimized parameters

## Best Practices

1. Use severity filtering for focused scans
2. Apply technology-specific tags when detected
3. Use `-rate-limit` for rate-limited targets
4. Use `-timeout` for slow targets
5. Use `-retries` for unreliable targets
6. Save results with `-o` flag

## Notes

- Severity levels: info, low, medium, high, critical
- Template sources: GitHub, local directory
- Update templates regularly: `nuclei -update-templates`
- Common tags: wordpress, drupal, joomla, cve, owasp
