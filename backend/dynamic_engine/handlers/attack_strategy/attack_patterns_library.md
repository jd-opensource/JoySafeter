# Attack Patterns Library

## Overview

- **Purpose**: Provide predefined attack patterns for common security testing scenarios with tool orchestration and parameter optimization
- **Category**: attack-patterns
- **Severity**: high
- **Tags**: attack-patterns, tool-orchestration, security-testing, penetration-testing, automation

## Context and Use-Cases

- **Automated security testing**: Execute standardized attack workflows
- **Penetration testing**: Conduct comprehensive security assessments
- **Vulnerability hunting**: Discover security issues systematically
- **Bug bounty programs**: Efficiently test targets for vulnerabilities
- **Security research**: Analyze attack patterns and tool effectiveness

## Procedure / Knowledge Detail

### Attack Pattern Framework

Each attack pattern consists of:
- **Pattern Name**: Descriptive identifier
- **Tools**: Ordered list of tools with priorities
- **Parameters**: Tool-specific configuration
- **Workflow**: Execution sequence and dependencies
- **Target Types**: Applicable target categories
- **Objectives**: Security testing goals

### 15 Attack Patterns

#### 1. Web Reconnaissance

**Purpose**: Comprehensive web application reconnaissance and technology discovery

**Tools** (8 total):

| Priority | Tool | Purpose | Parameters |
|----------|------|---------|-----------|
| 1 | nmap | Port scanning | scan_type: "-sV -sC", ports: "80,443,8080,8443" |
| 2 | httpx | HTTP probing | probe: True, tech_detect: True |
| 3 | katana | Web crawling | depth: 3, js_crawl: True |
| 4 | gau | URL collection | include_subs: True |
| 5 | waybackurls | Historical URLs | get_versions: False |
| 6 | nuclei | Vulnerability scanning | severity: "critical,high", tags: "tech" |
| 7 | dirsearch | Directory enumeration | extensions: "php,html,js,txt", threads: 30 |
| 8 | gobuster | Directory brute-force | mode: "dir", extensions: "php,html,js,txt" |

**Workflow**:
1. Scan ports and services (nmap)
2. Probe HTTP endpoints (httpx)
3. Crawl web application (katana)
4. Collect historical URLs (gau, waybackurls)
5. Scan for vulnerabilities (nuclei)
6. Enumerate directories (dirsearch, gobuster)

**Target Types**: Web Applications, API Endpoints
**Objectives**: Technology discovery, vulnerability identification, attack surface mapping

#### 2. API Testing

**Purpose**: Comprehensive API security testing and parameter discovery

**Tools** (6 total):

| Priority | Tool | Purpose | Parameters |
|----------|------|---------|-----------|
| 1 | httpx | Endpoint probing | probe: True, tech_detect: True |
| 2 | arjun | Parameter discovery | method: "GET,POST", stable: True |
| 3 | x8 | Parameter fuzzing | method: "GET", wordlist: "/usr/share/wordlists/x8/params.txt" |
| 4 | paramspider | Parameter collection | level: 2 |
| 5 | nuclei | API vulnerability scanning | tags: "api,graphql,jwt", severity: "high,critical" |
| 6 | ffuf | Parameter fuzzing | mode: "parameter", method: "POST" |

**Workflow**:
1. Probe API endpoints (httpx)
2. Discover parameters (arjun, paramspider)
3. Fuzz parameters (x8, ffuf)
4. Scan for API vulnerabilities (nuclei)

**Target Types**: API Endpoints, Web Applications
**Objectives**: Parameter discovery, API vulnerability detection, authentication bypass

#### 3. Network Discovery

**Purpose**: Comprehensive network reconnaissance and host enumeration

**Tools** (8 total):

| Priority | Tool | Purpose | Parameters |
|----------|------|---------|-----------|
| 1 | arp-scan | Local network discovery | local_network: True |
| 2 | rustscan | Fast port scanning | ulimit: 5000, scripts: True |
| 3 | nmap-advanced | Advanced scanning | scan_type: "-sS", os_detection: True, version_detection: True |
| 4 | masscan | Ultra-fast scanning | rate: 1000, ports: "1-65535", banners: True |
| 5 | enum4linux-ng | SMB enumeration | shares: True, users: True, groups: True |
| 6 | nbtscan | NetBIOS scanning | verbose: True |
| 7 | smbmap | SMB share mapping | recursive: True |
| 8 | rpcclient | RPC enumeration | commands: "enumdomusers;enumdomgroups;querydominfo" |

**Workflow**:
1. Discover local hosts (arp-scan)
2. Scan ports (rustscan, masscan)
3. Detect services and OS (nmap-advanced)
4. Enumerate SMB/Windows (enum4linux-ng, smbmap, rpcclient)
5. Scan NetBIOS (nbtscan)

**Target Types**: Network Hosts, Windows Domains
**Objectives**: Host discovery, service enumeration, credential harvesting

#### 4. Vulnerability Assessment

**Purpose**: Focused vulnerability scanning and exploitation

**Tools** (5 total):

| Priority | Tool | Purpose | Parameters |
|----------|------|---------|-----------|
| 1 | nuclei | Template-based scanning | severity: "critical,high,medium", update: True |
| 2 | jaeles | Signature-based scanning | threads: 20, timeout: 20 |
| 3 | dalfox | XSS detection | mining_dom: True, mining_dict: True |
| 4 | nikto | Web server scanning | comprehensive: True |
| 5 | sqlmap | SQL injection testing | crawl: 2, batch: True |

**Workflow**:
1. Run template-based scans (nuclei)
2. Signature scanning (jaeles)
3. XSS detection (dalfox)
4. Web server analysis (nikto)
5. SQL injection testing (sqlmap)

**Target Types**: Web Applications, APIs
**Objectives**: Vulnerability identification, exploitation proof-of-concept

#### 5. Comprehensive Network Pentest

**Purpose**: Full-scope network penetration testing

**Tools** (5 total):

| Priority | Tool | Purpose | Parameters |
|----------|------|---------|-----------|
| 1 | autorecon | Automated reconnaissance | port_scans: "top-1000-ports", service_scans: "default" |
| 2 | rustscan | Fast port scanning | ulimit: 5000, scripts: True |
| 3 | nmap-advanced | Advanced scanning | aggressive: True, nse_scripts: "vuln,exploit" |
| 4 | enum4linux-ng | SMB enumeration | shares: True, users: True, groups: True, policy: True |
| 5 | responder | Credential harvesting | wpad: True, duration: 180 |

**Workflow**:
1. Automated reconnaissance (autorecon)
2. Fast port scanning (rustscan)
3. Advanced vulnerability scanning (nmap-advanced)
4. SMB enumeration (enum4linux-ng)
5. Credential harvesting (responder)

**Target Types**: Network Hosts, Windows Domains
**Objectives**: Comprehensive network assessment, credential acquisition

#### 6. Binary Exploitation

**Purpose**: Binary analysis and exploitation

**Tools** (6 total):

| Priority | Tool | Purpose | Parameters |
|----------|------|---------|-----------|
| 1 | checksec | Security analysis | {} |
| 2 | ghidra | Reverse engineering | analysis_timeout: 300, output_format: "xml" |
| 3 | ropper | ROP gadget finding | gadget_type: "rop", quality: 2 |
| 4 | one-gadget | One-gadget exploitation | level: 1 |
| 5 | pwntools | Exploit development | exploit_type: "local" |
| 6 | gdb-peda | Debugging | commands: "checksec\ninfo functions\nquit" |

**Workflow**:
1. Analyze binary security (checksec)
2. Reverse engineering (ghidra)
3. Find ROP gadgets (ropper)
4. Identify one-gadgets (one-gadget)
5. Develop exploits (pwntools)
6. Debug and test (gdb-peda)

**Target Types**: Binary Files, Executables
**Objectives**: Vulnerability discovery, exploit development

#### 7. CTF PWN Challenge

**Purpose**: Capture-the-flag binary exploitation challenges

**Tools** (6 total):

| Priority | Tool | Purpose | Parameters |
|----------|------|---------|-----------|
| 1 | pwninit | Setup template | template_type: "python" |
| 2 | checksec | Security analysis | {} |
| 3 | ghidra | Reverse engineering | analysis_timeout: 180 |
| 4 | ropper | ROP gadget finding | gadget_type: "all", quality: 3 |
| 5 | angr | Symbolic execution | analysis_type: "symbolic" |
| 6 | one-gadget | One-gadget exploitation | level: 2 |

**Workflow**:
1. Setup exploit template (pwninit)
2. Analyze binary (checksec, ghidra)
3. Find gadgets (ropper)
4. Symbolic analysis (angr)
5. Identify exploits (one-gadget)

**Target Types**: Binary Files, CTF Challenges
**Objectives**: Challenge solution, exploit development

#### 8. AWS Security Assessment

**Purpose**: AWS cloud security evaluation

**Tools** (4 total):

| Priority | Tool | Purpose | Parameters |
|----------|------|---------|-----------|
| 1 | prowler | AWS auditing | provider: "aws", output_format: "json" |
| 2 | scout-suite | Multi-cloud scanning | provider: "aws" |
| 3 | cloudmapper | AWS mapping | action: "collect" |
| 4 | pacu | AWS exploitation | modules: "iam__enum_users_roles_policies_groups" |

**Workflow**:
1. AWS auditing (prowler)
2. Security scanning (scout-suite)
3. Infrastructure mapping (cloudmapper)
4. Privilege enumeration (pacu)

**Target Types**: Cloud Services (AWS)
**Objectives**: Misconfiguration detection, privilege escalation

#### 9. Kubernetes Security Assessment

**Purpose**: Kubernetes cluster security evaluation

**Tools** (3 total):

| Priority | Tool | Purpose | Parameters |
|----------|------|---------|-----------|
| 1 | kube-bench | CIS benchmarking | output_format: "json" |
| 2 | kube-hunter | Vulnerability scanning | report: "json" |
| 3 | falco | Runtime monitoring | duration: 120, output_format: "json" |

**Workflow**:
1. CIS benchmark testing (kube-bench)
2. Vulnerability scanning (kube-hunter)
3. Runtime monitoring (falco)

**Target Types**: Cloud Services (Kubernetes)
**Objectives**: Compliance verification, vulnerability detection

#### 10. Container Security Assessment

**Purpose**: Docker and container security evaluation

**Tools** (3 total):

| Priority | Tool | Purpose | Parameters |
|----------|------|---------|-----------|
| 1 | trivy | Image scanning | scan_type: "image", severity: "HIGH,CRITICAL" |
| 2 | clair | Vulnerability scanning | output_format: "json" |
| 3 | docker-bench-security | Security benchmark | {} |

**Workflow**:
1. Image vulnerability scanning (trivy)
2. Vulnerability analysis (clair)
3. Security benchmarking (docker-bench-security)

**Target Types**: Cloud Services (Containers)
**Objectives**: Image vulnerability detection, configuration hardening

#### 11. Infrastructure-as-Code Security Assessment

**Purpose**: IaC security evaluation (Terraform, CloudFormation, etc.)

**Tools** (3 total):

| Priority | Tool | Purpose | Parameters |
|----------|------|---------|-----------|
| 1 | checkov | IaC scanning | output_format: "json" |
| 2 | terrascan | Terraform scanning | scan_type: "all", output_format: "json" |
| 3 | trivy | Config scanning | scan_type: "config", severity: "HIGH,CRITICAL" |

**Workflow**:
1. IaC scanning (checkov)
2. Terraform analysis (terrascan)
3. Configuration scanning (trivy)

**Target Types**: Cloud Services (IaC)
**Objectives**: Misconfiguration detection, compliance verification

#### 12. Multi-Cloud Assessment

**Purpose**: Cross-cloud security evaluation

**Tools** (4 total):

| Priority | Tool | Purpose | Parameters |
|----------|------|---------|-----------|
| 1 | scout-suite | Multi-cloud scanning | provider: "aws" |
| 2 | prowler | AWS auditing | provider: "aws" |
| 3 | checkov | IaC scanning | framework: "terraform" |
| 4 | terrascan | Terraform scanning | scan_type: "all" |

**Workflow**:
1. Multi-cloud scanning (scout-suite)
2. AWS auditing (prowler)
3. IaC scanning (checkov, terrascan)

**Target Types**: Cloud Services (Multi-cloud)
**Objectives**: Cross-cloud security assessment

#### 13. Bug Bounty Reconnaissance

**Purpose**: Comprehensive reconnaissance for bug bounty programs

**Tools** (8 total):

| Priority | Tool | Purpose | Parameters |
|----------|------|---------|-----------|
| 1 | amass | Subdomain enumeration | mode: "enum", passive: False |
| 2 | subfinder | Subdomain discovery | silent: True, all_sources: True |
| 3 | httpx | HTTP probing | probe: True, tech_detect: True, status_code: True |
| 4 | katana | Web crawling | depth: 3, js_crawl: True, form_extraction: True |
| 5 | gau | URL collection | include_subs: True |
| 6 | waybackurls | Historical URLs | get_versions: False |
| 7 | paramspider | Parameter collection | level: 2 |
| 8 | arjun | Parameter discovery | method: "GET,POST", stable: True |

**Workflow**:
1. Subdomain enumeration (amass, subfinder)
2. HTTP probing (httpx)
3. Web crawling (katana)
4. URL collection (gau, waybackurls)
5. Parameter discovery (paramspider, arjun)

**Target Types**: Web Applications, APIs
**Objectives**: Attack surface mapping, vulnerability discovery

#### 14. Bug Bounty Vulnerability Hunting

**Purpose**: Vulnerability discovery and exploitation for bug bounties

**Tools** (5 total):

| Priority | Tool | Purpose | Parameters |
|----------|------|---------|-----------|
| 1 | nuclei | Template scanning | severity: "critical,high", tags: "rce,sqli,xss,ssrf" |
| 2 | dalfox | XSS detection | mining_dom: True, mining_dict: True |
| 3 | sqlmap | SQL injection | batch: True, level: 2, risk: 2 |
| 4 | jaeles | Signature scanning | threads: 20, timeout: 20 |
| 5 | ffuf | Fuzzing | match_codes: "200,204,301,302,307,401,403", threads: 40 |

**Workflow**:
1. Template scanning (nuclei)
2. XSS detection (dalfox)
3. SQL injection testing (sqlmap)
4. Signature scanning (jaeles)
5. Fuzzing (ffuf)

**Target Types**: Web Applications, APIs
**Objectives**: Vulnerability discovery, impact assessment

#### 15. Bug Bounty High-Impact Exploitation

**Purpose**: High-impact vulnerability exploitation for bug bounties

**Tools** (4 total):

| Priority | Tool | Purpose | Parameters |
|----------|------|---------|-----------|
| 1 | nuclei | Critical scanning | severity: "critical", tags: "rce,sqli,ssrf,lfi,xxe" |
| 2 | sqlmap | Advanced SQL injection | batch: True, level: 3, risk: 3, tamper: "space2comment" |
| 3 | jaeles | Advanced scanning | signatures: "rce,sqli,ssrf", threads: 30 |
| 4 | dalfox | Advanced XSS | blind: True, mining_dom: True, custom_payload: "alert(document.domain)" |

**Workflow**:
1. Critical vulnerability scanning (nuclei)
2. Advanced SQL injection (sqlmap)
3. Advanced signature scanning (jaeles)
4. Advanced XSS exploitation (dalfox)

**Target Types**: Web Applications, APIs
**Objectives**: High-impact vulnerability exploitation

## Pattern Selection Guide

### By Target Type

**Web Applications**:
- Web Reconnaissance
- API Testing
- Vulnerability Assessment
- Bug Bounty Reconnaissance
- Bug Bounty Vulnerability Hunting
- Bug Bounty High-Impact Exploitation

**Network Hosts**:
- Network Discovery
- Comprehensive Network Pentest

**Binary Files**:
- Binary Exploitation
- CTF PWN Challenge

**Cloud Services**:
- AWS Security Assessment
- Kubernetes Security Assessment
- Container Security Assessment
- Infrastructure-as-Code Security Assessment
- Multi-Cloud Assessment

### By Objective

**Reconnaissance**:
- Web Reconnaissance
- Network Discovery
- Bug Bounty Reconnaissance

**Vulnerability Scanning**:
- Vulnerability Assessment
- AWS Security Assessment
- Kubernetes Security Assessment
- Container Security Assessment
- Infrastructure-as-Code Security Assessment

**Exploitation**:
- Binary Exploitation
- CTF PWN Challenge
- Bug Bounty Vulnerability Hunting
- Bug Bounty High-Impact Exploitation

**Comprehensive Assessment**:
- Comprehensive Network Pentest
- Multi-Cloud Assessment

## Implementation Examples

### Example 1: Web Application Testing

```python
# Select web reconnaissance pattern
pattern = attack_patterns["web_reconnaissance"]

# Execute tools in priority order
for tool_config in pattern:
    tool_name = tool_config["tool"]
    priority = tool_config["priority"]
    params = tool_config["params"]

    # Execute tool with parameters
    result = execute_tool(tool_name, params)

    # Process results
    process_results(result)
```

### Example 2: Network Penetration Testing

```python
# Select comprehensive network pentest pattern
pattern = attack_patterns["comprehensive_network_pentest"]

# Execute tools sequentially
for tool_config in pattern:
    tool_name = tool_config["tool"]
    params = tool_config["params"]

    # Execute tool
    result = execute_tool(tool_name, params)

    # Feed results to next tool
    update_context(result)
```

### Example 3: Bug Bounty Workflow

```python
# Phase 1: Reconnaissance
recon_pattern = attack_patterns["bug_bounty_reconnaissance"]
recon_results = execute_pattern(recon_pattern)

# Phase 2: Vulnerability Hunting
hunting_pattern = attack_patterns["bug_bounty_vulnerability_hunting"]
hunting_results = execute_pattern(hunting_pattern)

# Phase 3: High-Impact Exploitation
impact_pattern = attack_patterns["bug_bounty_high_impact"]
impact_results = execute_pattern(impact_pattern)

# Consolidate findings
findings = consolidate_results([recon_results, hunting_results, impact_results])
```

## Tool Coverage

### Total Tools: 40+

**Network Scanning** (5): nmap, rustscan, masscan, nmap-advanced, arp-scan
**Web Scanning** (8): httpx, katana, gau, waybackurls, nuclei, dirsearch, gobuster, nikto
**Enumeration** (6): enum4linux-ng, nbtscan, smbmap, rpcclient, arjun, paramspider
**Vulnerability Scanning** (5): nuclei, jaeles, dalfox, sqlmap, ffuf
**Binary Analysis** (5): checksec, ghidra, ropper, one-gadget, pwntools
**Cloud Security** (8): prowler, scout-suite, cloudmapper, pacu, kube-bench, kube-hunter, trivy, clair
**IaC Security** (3): checkov, terrascan, trivy
**Other** (2): gdb-peda, pwninit, falco, docker-bench-security

## Related Knowledge Items

- **tool_effectiveness_scoring_system**: Tool effectiveness ratings
- **tool_selection_strategy**: How to select tools
- **parameter_optimization_framework**: Parameter tuning
- **target_analysis_workflow**: Target analysis process

## Best Practices

1. **Customize Patterns**: Adapt patterns to specific target characteristics
2. **Verify Permissions**: Ensure authorization before testing
3. **Monitor Resources**: Track CPU, memory, and network usage
4. **Handle Failures**: Implement fallback strategies
5. **Document Results**: Record all findings and tool outputs
6. **Iterate**: Refine patterns based on results
7. **Combine Patterns**: Mix patterns for comprehensive testing
8. **Prioritize**: Focus on high-impact vulnerabilities first
9. **Verify Findings**: Confirm vulnerabilities with multiple tools
10. **Report Responsibly**: Follow responsible disclosure practices
