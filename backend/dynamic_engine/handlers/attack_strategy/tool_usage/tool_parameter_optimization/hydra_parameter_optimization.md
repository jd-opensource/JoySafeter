# Hydra Parameter Optimization

## Overview

- **Purpose**: Intelligently optimize Hydra brute force tool parameters based on detected services from open ports
- **Category**: tool-optimization
- **Severity**: high
- **Tags**: hydra, parameter-optimization, brute-force, service-detection, port-based

## Procedure / Knowledge Detail

### Service Detection from Open Ports

**Port 22**: SSH service
- Parameter: `service: ssh`

**Port 21**: FTP service
- Parameter: `service: ftp`

**Port 80/443**: HTTP service
- Parameter: `service: http-get`

**Default**: SSH (fallback)
- Parameter: `service: ssh`

### Conservative Parameters

**Thread Count**: `-t 4`
- Purpose: Avoid account lockouts
- Speed: Slow but safe

**Wait Time**: `-w 30`
- Purpose: 30 seconds between attempts
- Detection: Very low

### Implementation Code

```python
def _optimize_hydra_params(self, profile: TargetProfile, context: Dict[str, Any]) -> Dict[str, Any]:
    """Optimize Hydra parameters"""
    params = {"target": profile.target}

    if 22 in profile.open_ports:
        params["service"] = "ssh"
    elif 21 in profile.open_ports:
        params["service"] = "ftp"
    elif 80 in profile.open_ports or 443 in profile.open_ports:
        params["service"] = "http-get"
    else:
        params["service"] = "ssh"

    params["additional_args"] = "-t 4 -w 30"
    return params
```

## Related Knowledge Items

- **target_analysis_workflow**: Provides open ports
- **tool_selection_strategy**: Selects hydra
- **attack_chain_generation_system**: Uses optimized parameters

## Best Practices

1. Use conservative parameters to avoid lockouts
2. Specify service type when known
3. Use `-L` for username list
4. Use `-P` for password list
5. Use `-o` to save results
6. Monitor for account lockouts
7. Use `-f` to stop after first success

## Notes

- Common services: ssh, ftp, http-get, smb, rdp
- Wordlist location: /usr/share/wordlists/
- Timeout: Default 30 seconds per attempt
- Thread count: 1-16 (default 4 for safety)
