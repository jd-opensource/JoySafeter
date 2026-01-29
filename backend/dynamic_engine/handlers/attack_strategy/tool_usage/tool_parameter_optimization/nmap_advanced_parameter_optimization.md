# Nmap Advanced Parameter Optimization

## Overview

- **Purpose**: Intelligently optimize advanced Nmap parameters with NSE scripts and OS detection
- **Category**: tool-optimization
- **Severity**: high
- **Tags**: nmap-advanced, parameter-optimization, nse-scripts, os-detection

## Procedure / Knowledge Detail

### Stealth/Aggressive Mode Selection

**Stealth Mode**:
- Timing: `-T2`
- NSE Scripts: Safe scripts only
- OS Detection: Disabled

**Aggressive Mode**:
- Timing: `-T4`
- NSE Scripts: Default + intrusive
- OS Detection: Enabled

### NSE Script Selection by Target Type

**WEB_APPLICATION**:
- Scripts: http-*, ssl-*, web-*

**NETWORK_HOST**:
- Scripts: smb-*, snmp-*, ssh-*

### Implementation Code

```python
def _optimize_nmap_advanced_params(self, profile: TargetProfile, context: Dict[str, Any]) -> Dict[str, Any]:
    """Optimize advanced Nmap parameters"""
    params = {"target": profile.target}

    if context.get("stealth", False):
        params["timing"] = "-T2"
        params["scripts"] = "safe"
        params["os_detection"] = False
    else:
        params["timing"] = "-T4"
        params["scripts"] = "default,intrusive"
        params["os_detection"] = True

    if profile.target_type == TargetType.WEB_APPLICATION:
        params["scripts"] = "http-*,ssl-*,web-*"
    elif profile.target_type == TargetType.NETWORK_HOST:
        params["scripts"] = "smb-*,snmp-*,ssh-*"

    return params
```

## Related Knowledge Items

- **tool_selection_strategy**: Selects nmap-advanced
- **attack_chain_generation_system**: Uses optimized parameters
- **parameter_optimization_system**: Framework for optimization

## Best Practices

1. Use safe scripts for stealth
2. Use intrusive scripts for authorized testing
3. Enable OS detection for network reconnaissance
4. Select scripts based on target type
5. Monitor for IDS/IPS triggers
6. Use appropriate timing profiles

## Notes

- NSE scripts: safe, default, discovery, intrusive, all
- Timing profiles: T0-T5 (paranoid to insane)
- OS detection requires root/admin privileges
- Script selection affects scan time significantly
