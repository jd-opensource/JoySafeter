# Gobuster Parameter Optimization

## Overview

- **Purpose**: Intelligently optimize Gobuster directory enumeration parameters based on detected technologies and execution context
- **Category**: tool-optimization
- **Severity**: high
- **Tags**: gobuster, parameter-optimization, directory-enumeration, technology-specific

## Context and Use-Cases

Gobuster parameter optimization is essential for:

- **Technology-Specific Extensions**: Adapt file extensions based on detected tech stack
- **Thread Optimization**: Balance speed vs resource usage
- **Wordlist Selection**: Choose appropriate wordlists for target
- **Aggressive vs Conservative**: Adjust based on stealth requirements

## Procedure / Knowledge Detail

### Technology-Specific Extension Selection

**PHP Detection**:
- Extensions: `-x php,html,txt,xml`
- Purpose: Find PHP files and related resources

**ASP.NET Detection**:
- Extensions: `-x asp,aspx,html,txt`
- Purpose: Find ASP.NET application files

**Java Detection**:
- Extensions: `-x jsp,html,txt,xml`
- Purpose: Find JSP application files

**Default**:
- Extensions: `-x html,php,txt,js`
- Purpose: Common web file types

### Context-Aware Thread Adjustment

**Aggressive Mode** (`context.get("aggressive", False)`):
- Threads: `-t 50`
- Speed: Very fast
- Detection: Higher

**Conservative Mode** (default):
- Threads: `-t 20`
- Speed: Moderate
- Detection: Lower

### Implementation Code

```python
def _optimize_gobuster_params(self, profile: TargetProfile, context: Dict[str, Any]) -> Dict[str, Any]:
    """Optimize Gobuster parameters"""
    params = {"url": profile.target, "mode": "dir"}

    # Technology-specific extensions
    if TechnologyStack.PHP in profile.technologies:
        params["additional_args"] = "-x php,html,txt,xml"
    elif TechnologyStack.DOTNET in profile.technologies:
        params["additional_args"] = "-x asp,aspx,html,txt"
    elif TechnologyStack.JAVA in profile.technologies:
        params["additional_args"] = "-x jsp,html,txt,xml"
    else:
        params["additional_args"] = "-x html,php,txt,js"

    # Thread adjustment
    if context.get("aggressive", False):
        params["additional_args"] += " -t 50"
    else:
        params["additional_args"] += " -t 20"

    return params
```

## Related Knowledge Items

- **technology_detection_heuristics**: Detects technologies
- **tool_selection_strategy**: Selects gobuster
- **attack_chain_generation_system**: Uses optimized parameters

## Best Practices

1. Match extensions to detected technology
2. Use appropriate wordlists (common.txt, big.txt)
3. Adjust threads based on target responsiveness
4. Use `-s` flag to show status codes
5. Use `-o` flag to save results
6. Consider rate limiting for stealth

## Notes

- Common extensions: php, asp, aspx, jsp, html, txt, js
- Wordlist location: /usr/share/wordlists/
- Status codes: 200 (found), 301/302 (redirect), 403 (forbidden)
- Timeout: Default 10 seconds per request
