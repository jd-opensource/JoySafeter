# Tools

# OpenClaw Security Checker Tools

## Common response fields

- success: boolean
- check_name: string identifier of the check
- severity: "CRITICAL"|"HIGH"|"MEDIUM"|"LOW"
- score_deduction: integer points deducted
- details: human-readable description of the finding

## Configuration parsing

- parse_openclaw_config(config_path="~/.openclaw/openclaw.json"): Parse and return the full OpenClaw configuration as JSON. Returns structured config object for downstream checks.
- extract_gateway_config(config): Extract gateway-specific settings (port, bind, auth, CORS, trustedProxies). Returns gateway configuration subset.
- extract_tools_config(config): Extract tool permission settings (profile, fs, sessions). Returns tools configuration subset.
- extract_model_config(config): Extract model provider settings (baseUrl, contextWindow, maxTokens). Returns model configuration subset.

## Credential scanning

- scan_config_secrets(config_path, patterns=["sk-", "key-", "token:", "password:", "secret:"]): Scan configuration file for hardcoded credentials using regex patterns. Returns array of matches with line numbers.
- scan_env_secrets(env_file=".env", additional_patterns=[]): Scan environment files for exposed credentials. Returns matches with variable names.
- scan_log_secrets(log_dir="~/.openclaw/logs", max_files=50): Scan recent log files for accidentally logged credentials. Returns matches with file paths and line numbers.
- calculate_token_entropy(token): Calculate Shannon entropy of an authentication token. Returns entropy value (minimum safe threshold: 4.0).

## Permission checks

- check_file_permissions(path, expected_mode="600"): Verify file permission bits match expected value. Returns current mode and pass/fail status.
- check_directory_permissions(path, expected_mode="700", recursive=False): Verify directory permissions, optionally recursive. Returns list of non-compliant paths.
- check_running_user(): Detect current process UID/GID. Returns user info and whether running as root.
- check_workspace_isolation(config): Verify workspaceOnly setting and actual filesystem access scope. Returns isolation status.

## Quarantine inspection

- scan_quarantine(quarantine_dir="~/.openclaw/_quarantine"): List all quarantined skills with metadata (quarantine reason, date, original path). Returns quarantine manifest.
- verify_quarantine_integrity(quarantine_dir): Verify quarantined skills cannot be loaded by checking skill loader config. Returns integrity status.

## Integrity verification

- compute_file_hash(path, algorithm="sha256"): Compute cryptographic hash of a file. Returns hex digest.
- verify_baseline(baseline_file, target_dir): Compare current file hashes against a stored baseline. Returns list of modified/added/deleted files.
- generate_baseline(target_dir, output_file): Generate a hash baseline for all files in directory. Writes baseline JSON file.

## Network checks

- check_gateway_exposure(port, bind_address): Verify gateway port accessibility from outside container. Returns exposure status.
- check_outbound_rules(): Inspect iptables/nftables for outbound network restrictions. Returns rule summary.
- check_trusted_proxies(proxies_list): Analyze trusted proxy CIDR ranges for overly broad configurations. Returns analysis with scope assessment.
- check_dns_resolution(config): Verify DNS resolution is restricted to expected resolvers. Returns DNS configuration.

## Log audit

- analyze_recent_logs(log_dir, hours=24, patterns=[]): Scan recent logs for suspicious patterns (mass failures, sensitive operations). Returns matched log entries.
- detect_redline_triggers(log_dir): Search for security redline trigger records in logs. Returns trigger events with timestamps.
- check_log_integrity(log_dir): Verify log files are append-only and not tampered. Returns integrity assessment.

## Scoring

- calculate_security_score(findings): Aggregate all findings and compute final security score (0-100). Returns score, grade (A-F), and summary.
- generate_report(findings, format="text"): Generate formatted security report. format: "text"|"json"|"markdown". Returns formatted report string.
