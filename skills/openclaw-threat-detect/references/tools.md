# Tools

# OpenClaw Threat Detection Tools

## Common response fields

- success: boolean
- threat_id: unique identifier for the detection
- severity: "CRITICAL"|"HIGH"|"MEDIUM"|"LOW"
- category: string attack category
- mitre_attack: MITRE ATT&CK technique ID
- confidence: float (0.0-1.0) detection confidence score
- recommendation: suggested response action

## Command scanning

- scan_command(command, context=""): Analyze a single command string against all threat detection rules. context provides additional info (working directory, parent process, triggering skill). Returns array of matched threats.
- scan_command_batch(commands, correlate=True): Analyze an array of commands. When correlate=True, performs multi-step attack chain detection across commands. Returns threats with optional chain metadata.
- scan_shell_history(history_file="~/.bash_history", lines=1000): Scan recent shell history for threat patterns. Returns chronologically ordered threat matches.

## File scanning

- scan_file(file_path, check_encoding=True, check_hidden_chars=True): Scan a file for malicious patterns, encoded payloads, and hidden characters. Returns array of findings with line numbers.
- scan_directory(dir_path, recursive=True, file_types=["sh", "py", "js", "md"], max_depth=5): Scan all matching files in a directory. Returns aggregated findings per file.
- scan_code_block(code, language="bash"): Extract and analyze a code block (from SKILL.md). language hint guides parser selection. Returns findings.
- detect_obfuscation(content): Detect obfuscation techniques (base64, hex encoding, eval chains, variable substitution tricks). Returns obfuscation indicators with decoded content.

## Network monitoring

- check_outbound_connections(pid=""): List active outbound network connections. If pid specified, filter to that process. Returns connection list with destination IPs and ports.
- analyze_dns_queries(log_file="", duration_seconds=60): Capture or analyze DNS query log for suspicious patterns (high-entropy subdomains, unusual TLDs). Returns suspicious queries.
- check_destination_reputation(ip_or_domain, threat_intel_sources=["builtin"]): Check if destination IP or domain appears in threat intelligence feeds. Returns reputation score and match details.

## Behavior correlation

- correlate_events(events, time_window_seconds=300): Correlate multiple events within a time window to detect multi-step attack patterns. Returns identified attack chains.
- detect_recon_pattern(commands): Identify reconnaissance behavior (file listing, env dumping, network scanning) that often precedes an attack. Returns recon score.
- detect_staging_pattern(commands): Identify data staging behavior (file copying, archiving, encoding) that precedes exfiltration. Returns staging indicators.

## Prompt analysis

- scan_prompt_injection(text, check_hidden=True): Scan text content for prompt injection patterns (role override, instruction hijack, hidden directives). Returns injection indicators.
- detect_indirect_injection(document_content): Analyze document or web content that an Agent might process for embedded malicious instructions. Returns injection vectors found.
- analyze_agent_tool_chain(tool_calls): Analyze a sequence of Agent tool invocations for suspicious patterns (unauthorized escalation, excessive resource use). Returns chain analysis.

## Alert management

- create_alert(threat, instance_id=""): Generate a structured alert from a detection finding. Returns formatted alert object.
- classify_severity(threat_type, confidence, context): Determine final severity based on threat type, confidence score, and execution context. Returns severity classification.
- generate_ioc(threats): Extract Indicators of Compromise (IPs, domains, file hashes, command patterns) from detected threats. Returns IOC list.
