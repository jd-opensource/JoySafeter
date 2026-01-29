# Nmap Parameter Optimization

## Overview

- **Purpose**: Intelligently optimize Nmap network scanner parameters based on target type and execution context
- **Category**: tool-optimization
- **Severity**: high
- **Tags**: nmap, parameter-optimization, network-scanning, target-type-specific, context-aware

## Context and Use-Cases

Nmap parameter optimization is essential for:

- **Target-Specific Scanning**: Adapt scan parameters to target type
- **Stealth Testing**: Reduce detection probability with conservative timing
- **Aggressive Scanning**: Maximize speed for authorized testing
- **Port Selection**: Choose relevant ports based on target type
- **Service Detection**: Enable version and script scanning when needed

## Procedure / Knowledge Detail

### Target Type-Specific Optimization

**WEB_APPLICATION**:
- Scan type: `-sV -sC` (version and script scanning)
- Ports: 80, 443, 8080, 8443, 8000, 9000
- Purpose: Detect web services and vulnerabilities

**NETWORK_HOST**:
- Scan type: `-sS -O` (SYN scan with OS detection)
- Ports: Top 1000 ports
- Purpose: Network discovery and OS fingerprinting

### Context-Aware Timing

**Stealth Mode** (`context.get("stealth", False)`):
- Timing: `-T2` (Polite)
- Detection: Very low
- Speed: Slow (~5-10 minutes)

**Aggressive Mode** (default):
- Timing: `-T4` (Aggressive)
- Detection: Higher
- Speed: Fast (~1-2 minutes)

### Implementation Code

```python
def _optimize_nmap_params(self, profile: TargetProfile, context: Dict[str, Any]) -> Dict[str, Any]:
    """Optimize Nmap parameters"""
    params = {"target": profile.target}

    if profile.target_type == TargetType.WEB_APPLICATION:
        params["scan_type"] = "-sV -sC"
        params["ports"] = "80,443,8080,8443,8000,9000"
    elif profile.target_type == TargetType.NETWORK_HOST:
        params["scan_type"] = "-sS -O"
        params["additional_args"] = "--top-ports 1000"

    if context.get("stealth", False):
        params["additional_args"] = params.get("additional_args", "") + " -T2"
    else:
        params["additional_args"] = params.get("additional_args", "") + " -T4"

    return params
```

## Related Knowledge Items

- **tool_selection_strategy**: Selects nmap for network scanning
- **attack_chain_generation_system**: Uses optimized nmap parameters
- **parameter_optimization_system**: Framework for optimization

## Best Practices

1. Use `-sV` for service version detection
2. Use `-sC` for NSE script scanning
3. Use `-T2` for stealth, `-T4` for speed
4. Select ports based on target type
5. Monitor scan progress with `-v` flag
6. Save results with `-oA` for multiple formats

## Notes

- Timing profiles: T0-T5 (paranoid to insane)
- Common ports: 80, 443, 22, 21, 3306, 5432
- NSE scripts: Default, discovery, safe, intrusive
- OS detection requires root/admin privileges
