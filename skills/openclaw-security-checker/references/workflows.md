# Workflows

# OpenClaw Security Checker Workflows

## Configuration security scan

- parse_openclaw_config: config_path "~/.openclaw/openclaw.json"
- Check for:
  - API Key exposure: regex match `sk-[a-zA-Z0-9]+`, `key-[a-zA-Z0-9]+`, `Bearer [a-zA-Z0-9]+`
  - Gateway bind scope: `gateway.bind` should be `localhost` or `127.0.0.1`, not `0.0.0.0` or `lan`
  - Tool profile: `tools.profile` should be `restricted` or `standard`, not `full`
  - CORS origins: `allowedOrigins` should not contain `*`
  - Device auth: `dangerouslyDisableDeviceAuth` should be `false`
  - Auth token: minimum length 32, entropy >= 4.0
  - TLS: gateway should use HTTPS in production
  - Auto-update: `update.checkOnStart` should be `true`
- scan_config_secrets: config_path, patterns ["sk-", "key-", "token:", "password:", "secret:", "apiKey:"]
- scan_env_secrets: check for `.env` files in config and workspace directories
- Severity mapping:
  - CRITICAL: plaintext API key found, gateway bound to 0.0.0.0
  - HIGH: device auth disabled, weak token, tools profile full
  - MEDIUM: CORS too broad, TLS not configured, auto-update disabled

## Permission and isolation check

- check_running_user: verify UID != 0 (not root)
- check_file_permissions: "~/.openclaw/openclaw.json", expected_mode "600"
- check_directory_permissions: "~/.openclaw/", expected_mode "700", recursive True
- check_directory_permissions: "/workspace/skills/", expected_mode "750"
- check_workspace_isolation: extract_tools_config, verify `fs.workspaceOnly` is True
- Check for:
  - Root execution: process running as UID 0 is CRITICAL
  - Config readable by others: permission bits allow group/world read
  - Workspace directory writable by others: 777 or 775 on workspace dirs
  - Filesystem isolation disabled: `tools.fs.workspaceOnly` is False
- scan_quarantine: check if quarantined skills exist, list them with reasons
- verify_quarantine_integrity: ensure quarantined skills cannot bypass loader

## Network security check

- check_gateway_exposure: port from config, bind_address from config
- check_trusted_proxies: proxies_list from `gateway.trustedProxies`
- check_outbound_rules: inspect container iptables
- check_dns_resolution: verify DNS config
- Check for:
  - Gateway reachable from outside container network: CRITICAL
  - Trusted proxies include /8 or /16 blocks: MEDIUM (overly broad)
  - No outbound network restrictions: HIGH
  - DNS resolvers outside expected range: MEDIUM

## Integrity verification

- generate_baseline: first run creates baseline at `~/.openclaw/.security-baseline.json`
- verify_baseline: subsequent runs compare against stored baseline
- compute_file_hash: check core OpenClaw binaries and config files
- Check for:
  - Modified core files (compared to baseline): HIGH
  - New unexpected files in core directories: MEDIUM
  - Baseline file missing (first run): LOW (informational)
  - Baseline file itself modified: CRITICAL

## Log audit

- analyze_recent_logs: log_dir "~/.openclaw/logs", hours 24
  - Patterns to detect:
    - Mass authentication failures (>10 in 1 hour)
    - Sensitive file access (config, keys, tokens)
    - Tool execution spikes (>100 commands in 5 minutes)
    - Unusual hours activity (02:00-05:00 local time)
- detect_redline_triggers: search for explicit security boundary violations
- check_log_integrity: verify logs are append-only, not truncated or modified
- Severity mapping:
  - CRITICAL: redline triggered, logs tampered
  - HIGH: sensitive operations without audit trail
  - MEDIUM: suspicious activity patterns, unusual timing
  - LOW: informational entries, minor anomalies

## Score calculation and reporting

- calculate_security_score: aggregate all findings
  - Deduction rules:
    - CRITICAL finding: -15 to -20 points each
    - HIGH finding: -10 points each
    - MEDIUM finding: -5 points each
    - LOW finding: -2 to -3 points each
  - Floor: 0 (score cannot go below 0)
- generate_report: format "text" for terminal, "json" for automation, "markdown" for documentation
- Grade assignment:
  - A (90-100): pass, schedule periodic re-check
  - B (80-89): pass with warnings, fix in next maintenance window
  - C (70-79): conditional pass, fix within one week
  - D (60-69): fail, requires immediate attention
  - F (0-59): critical fail, stop service and remediate
