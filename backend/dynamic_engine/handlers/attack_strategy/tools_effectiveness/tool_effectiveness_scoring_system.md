# Tool Effectiveness Scoring System

## Overview

- **Purpose**: Rate and rank security tools based on their effectiveness for specific target types, enabling intelligent tool selection for penetration testing campaigns
- **Category**: tooling
- **Severity**: high
- **Tags**: tool-selection, effectiveness-scoring, target-type-specific, penetration-testing

## Context and Use-Cases
- **Intelligent tool selection**: Automatically choose the most effective tools for a given target type
- **Attack chain optimization**: Prioritize tools with highest success probability in attack sequences
- **Resource allocation**: Focus on high-effectiveness tools to maximize penetration testing efficiency
- **Tool comparison**: Compare relative effectiveness of similar tools within the same category
- **Capability mapping**: Understand which tools excel at specific target types

## Procedure / Knowledge Detail

### 1. Effectiveness Score Ranges
All tool effectiveness scores are normalized to a 0.0-1.0 scale:
- **0.95-1.0**: Excellent - Highly specialized and effective for this target type
- **0.85-0.94**: Very Good - Strong effectiveness with minor limitations
- **0.75-0.84**: Good - Solid effectiveness with some limitations
- **0.65-0.74**: Fair - Moderate effectiveness, useful but not primary choice
- **Below 0.65**: Limited - Minimal effectiveness for this target type

### 2. Target Type Categories
The system evaluates tool effectiveness across six distinct target types:

#### WEB_APPLICATION
Web applications including traditional websites, web services, and web-based platforms.

**High-effectiveness tools (0.9+)**:
- nuclei (0.95) - Vulnerability scanning with extensive templates
- wpscan (0.95) - WordPress-specific vulnerability detection
- gobuster (0.9) - Directory and DNS enumeration
- sqlmap (0.9) - SQL injection detection and exploitation
- ffuf (0.9) - Fast fuzzing framework
- burpsuite (0.9) - Comprehensive web application testing

**Very good tools (0.85-0.89)**:
- nikto (0.85) - Web server scanning
- feroxbuster (0.85) - Content discovery
- httpx (0.85) - HTTP probing and technology detection
- dirsearch (0.87) - Directory enumeration
- katana (0.88) - Web crawling and endpoint discovery
- x8 (0.88) - Parameter discovery
- paramspider (0.85) - Parameter mining

**Good tools (0.75-0.84)**:
- nmap (0.8) - Network and service discovery
- gau (0.82) - URL collection from archives
- waybackurls (0.8) - Historical URL retrieval
- jaeles (0.92) - Web vulnerability scanning
- dalfox (0.93) - XSS detection and exploitation

**Utility tools (0.7-0.75)**:
- anew (0.7) - URL deduplication
- qsreplace (0.75) - Query string replacement
- uro (0.7) - URL normalization

#### NETWORK_HOST
Network hosts including servers, workstations, and network infrastructure.

**Excellent tools (0.95+)**:
- nmap (0.95) - Comprehensive network scanning and service detection
- nmap-advanced (0.97) - Enhanced Nmap with NSE scripts for deeper analysis
- autorecon (0.95) - Fully automated reconnaissance framework

**Very good tools (0.85-0.94)**:
- masscan (0.92) - Ultra-fast port scanning with intelligent rate limiting
- rustscan (0.9) - Fast port scanner with Nmap integration
- enum4linux-ng (0.88) - Enhanced SMB/CIFS enumeration
- responder (0.88) - Credential harvesting via LLMNR/NBT-NS
- smbmap (0.85) - SMB share enumeration and access testing
- arp-scan (0.85) - ARP-based network discovery
- netexec (0.85) - Network execution and credential testing

**Good tools (0.75-0.84)**:
- enum4linux (0.8) - SMB/CIFS enumeration
- hydra (0.8) - Credential brute-forcing
- rpcclient (0.82) - RPC client for Windows enumeration

**Fair tools (0.65-0.74)**:
- nbtscan (0.75) - NetBIOS scanning
- amass (0.7) - Subdomain enumeration (limited for direct host testing)

#### API_ENDPOINT
API endpoints including REST APIs, GraphQL endpoints, and other API services.

**Excellent tools (0.95+)**:
- arjun (0.95) - API parameter discovery with high accuracy

**Very good tools (0.85-0.94)**):
- x8 (0.92) - Hidden parameter discovery
- nuclei (0.9) - API vulnerability scanning
- httpx (0.9) - API probing and technology detection
- paramspider (0.88) - Parameter extraction from archives
- jaeles (0.88) - API vulnerability detection

**Good tools (0.75-0.84)**:
- ffuf (0.85) - Fuzzing API endpoints
- katana (0.85) - API endpoint discovery
- postman (0.8) - API testing and documentation

#### CLOUD_SERVICE
Cloud infrastructure and services including AWS, Azure, GCP, Kubernetes, and containers.

**Excellent tools (0.95+)**:
- prowler (0.95) - AWS security assessment and compliance checking

**Very good tools (0.85-0.94)**:
- scout-suite (0.92) - Multi-cloud security assessment
- trivy (0.9) - Container and artifact vulnerability scanning
- kube-hunter (0.9) - Kubernetes penetration testing
- checkov (0.9) - Infrastructure-as-Code security scanning

**Good tools (0.75-0.84)**:
- cloudmapper (0.88) - AWS network visualization
- kube-bench (0.88) - Kubernetes CIS benchmark compliance
- docker-bench-security (0.85) - Docker security benchmarking
- falco (0.87) - Runtime security monitoring
- clair (0.85) - Container image vulnerability analysis
- terrascan (0.88) - Infrastructure-as-Code security scanning
- pacu (0.85) - AWS exploitation framework

#### BINARY_FILE
Binary files including executables, libraries, and firmware for reverse engineering and exploitation.

**Excellent tools (0.95+)**:
- ghidra (0.95) - Comprehensive binary analysis and decompilation

**Very good tools (0.85-0.94)**:
- radare2 (0.9) - Reverse engineering framework
- pwntools (0.9) - Exploit development library
- gdb-peda (0.92) - Enhanced GDB debugging
- ropper (0.88) - ROP gadget finder
- pwninit (0.85) - CTF environment setup

**Good tools (0.75-0.84)**:
- angr (0.88) - Symbolic execution engine
- gdb (0.85) - GNU debugger
- binwalk (0.8) - Binary firmware analysis
- libc-database (0.8) - Libc version identification
- ropgadget (0.85) - ROP gadget extraction
- objdump (0.75) - Binary disassembly
- checksec (0.75) - Binary security properties

**Fair tools (0.65-0.74)**:
- strings (0.7) - String extraction from binaries
- one-gadget (0.82) - One-gadget RCE finder (libc-specific)

### 3. Effectiveness Scoring Methodology

#### Factors Considered
1. **Tool Specialization**: How specialized is the tool for this target type?
2. **Coverage**: What percentage of target vulnerabilities can this tool detect?
3. **Accuracy**: How many false positives/negatives does the tool produce?
4. **Speed**: How quickly does the tool complete its analysis?
5. **Reliability**: How consistently does the tool work across different environments?
6. **Integration**: How well does the tool integrate with other tools?

#### Score Calibration
- **0.95-1.0**: Tool is specifically designed for this target type with minimal false positives
- **0.85-0.94**: Tool is highly effective with good coverage and reliability
- **0.75-0.84**: Tool is useful but has some limitations or false positives
- **0.65-0.74**: Tool has limited effectiveness but can provide supplementary information
- **Below 0.65**: Tool is not recommended for this target type

### 4. Tool Categories by Function

#### Network Scanning & Discovery
- nmap, nmap-advanced, masscan, rustscan, arp-scan, nbtscan

#### Directory & Endpoint Discovery
- gobuster, dirsearch, feroxbuster, ffuf, wfuzz, katana

#### Web Application Testing
- nikto, nuclei, jaeles, dalfox, sqlmap, wpscan, burpsuite

#### Parameter Discovery
- arjun, paramspider, x8, gau, waybackurls

#### SMB/Windows Enumeration
- enum4linux, enum4linux-ng, smbmap, rpcclient, responder, netexec

#### Credential Testing
- hydra, hashcat, john

#### Cloud Security
- prowler, scout-suite, cloudmapper, pacu, checkov, terrascan

#### Container & Kubernetes
- trivy, clair, kube-hunter, kube-bench, docker-bench-security, falco

#### Binary Analysis & Exploitation
- ghidra, radare2, gdb, gdb-peda, angr, pwntools, ropper, one-gadget, binwalk, checksec

### 5. Dynamic Score Adjustment

While base scores are static, they can be adjusted based on:
- **Target-specific factors**: Presence of WAF, rate limiting, or security controls
- **Tool configuration**: Optimization parameters and custom wordlists
- **Environmental factors**: Network conditions, tool availability, permissions
- **Historical performance**: Previous tool performance on similar targets

## Examples

### Example 1: Web Application Assessment
```python
# Selecting tools for web application penetration testing
target_type = "web_application"
effectiveness_scores = {
    "nuclei": 0.95,      # Primary choice - highest effectiveness
    "wpscan": 0.95,      # If WordPress detected
    "gobuster": 0.9,     # Directory enumeration
    "sqlmap": 0.9,       # SQL injection testing
    "ffuf": 0.9,         # Fuzzing
    "burpsuite": 0.9,    # Manual testing
    "nikto": 0.85,       # Web server scanning
    "feroxbuster": 0.85, # Content discovery
    "httpx": 0.85,       # Technology detection
}

# Tools are selected in descending order of effectiveness
selected_tools = sorted(effectiveness_scores.items(),
                       key=lambda x: x[1],
                       reverse=True)
# Result: nuclei (0.95), wpscan (0.95), gobuster (0.9), sqlmap (0.9), ...
```

### Example 2: Network Host Assessment
```python
# Selecting tools for network host penetration testing
target_type = "network_host"
effectiveness_scores = {
    "nmap-advanced": 0.97,    # Most comprehensive
    "nmap": 0.95,             # Standard network scanning
    "autorecon": 0.95,        # Automated reconnaissance
    "masscan": 0.92,          # Fast port scanning
    "rustscan": 0.9,          # Fast scanning with Nmap
    "enum4linux-ng": 0.88,    # SMB enumeration
    "responder": 0.88,        # Credential harvesting
    "smbmap": 0.85,           # SMB share access
    "arp-scan": 0.85,         # ARP discovery
}

# Primary tools for comprehensive assessment
primary_tools = [tool for tool, score in effectiveness_scores.items()
                 if score >= 0.9]
# Result: nmap-advanced, nmap, autorecon
```

### Example 3: API Endpoint Assessment
```python
# Selecting tools for API endpoint testing
target_type = "api_endpoint"
effectiveness_scores = {
    "arjun": 0.95,        # Parameter discovery - highest effectiveness
    "x8": 0.92,           # Hidden parameter discovery
    "nuclei": 0.9,        # API vulnerability scanning
    "httpx": 0.9,         # API probing
    "paramspider": 0.88,  # Parameter extraction
    "jaeles": 0.88,       # Vulnerability detection
    "ffuf": 0.85,         # Endpoint fuzzing
    "katana": 0.85,       # Endpoint discovery
}

# Select top 3 tools for quick assessment
quick_assessment = sorted(effectiveness_scores.items(),
                         key=lambda x: x[1],
                         reverse=True)[:3]
# Result: arjun (0.95), x8 (0.92), nuclei (0.9)
```

### Example 4: Cloud Service Assessment
```python
# Selecting tools for AWS security assessment
target_type = "cloud_service"
effectiveness_scores = {
    "prowler": 0.95,           # AWS-specific - highest effectiveness
    "scout-suite": 0.92,       # Multi-cloud assessment
    "trivy": 0.9,              # Container scanning
    "kube-hunter": 0.9,        # Kubernetes testing
    "checkov": 0.9,            # IaC scanning
    "cloudmapper": 0.88,       # AWS visualization
    "kube-bench": 0.88,        # K8s compliance
    "docker-bench-security": 0.85,  # Docker security
}

# AWS-specific tools for comprehensive assessment
aws_tools = ["prowler", "scout-suite", "cloudmapper", "pacu"]
```

### Example 5: Binary File Analysis
```python
# Selecting tools for binary reverse engineering
target_type = "binary_file"
effectiveness_scores = {
    "ghidra": 0.95,        # Comprehensive analysis - highest effectiveness
    "radare2": 0.9,        # Reverse engineering framework
    "pwntools": 0.9,       # Exploit development
    "gdb-peda": 0.92,      # Enhanced debugging
    "ropper": 0.88,        # ROP gadget finding
    "pwninit": 0.85,       # CTF setup
    "angr": 0.88,          # Symbolic execution
    "gdb": 0.85,           # Standard debugging
}

# Primary tools for comprehensive binary analysis
primary_tools = [tool for tool, score in effectiveness_scores.items()
                 if score >= 0.9]
# Result: ghidra, gdb-peda, radare2, pwntools
```

## Related Knowledge Items
- **tool_selection_strategy**: How to select tools based on effectiveness scores
- **target_type_determination**: How to classify targets into these categories
- **attack_chain_generation_system**: How effectiveness scores are used in attack chain generation
- **parameter_optimization_framework**: How to optimize tool parameters for maximum effectiveness

## Mitigation & Best Practices
1. **Regular Updates**: Update effectiveness scores as new tools emerge or tool capabilities change
2. **Performance Monitoring**: Track actual tool performance and adjust scores based on real-world results
3. **Contextual Adjustment**: Adjust scores based on target-specific factors (WAF, rate limiting, etc.)
4. **Tool Combination**: Use multiple tools with complementary effectiveness for comprehensive coverage
5. **Fallback Strategies**: Have alternative tools available when primary tools fail
6. **Version Awareness**: Account for tool version differences in effectiveness scoring
7. **Environment Testing**: Test tools in the target environment before full deployment
