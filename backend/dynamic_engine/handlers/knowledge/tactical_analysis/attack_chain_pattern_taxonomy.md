# Attack Chain Pattern Taxonomy

## Overview
- **Purpose**: Classify vulnerabilities and CVE descriptions into MITRE ATT&CK tactical stages using keyword-based pattern matching for automated attack chain discovery
- **Category**: tactical_analysis
- **Severity**: info
- **Tags**: attack-chain, mitre-attack, threat-modeling, cve-classification, kill-chain, TA0001, TA0004, TA0003, TA0008, TA0010

## Context and Use-Cases
- **Automated CVE Classification**: Parse CVE descriptions to automatically tag vulnerabilities by attack stage
- **Threat Modeling**: Identify potential multi-stage attack paths by chaining vulnerabilities across tactical stages
- **Red Team Planning**: Select vulnerabilities that form complete attack chains (Initial Access → Privilege Escalation → Persistence)
- **Blue Team Prioritization**: Focus defensive resources on vulnerabilities that enable critical attack stages
- **Threat Intelligence Enrichment**: Enhance vulnerability feeds with tactical context for better risk assessment

## Key Parameters and Inputs
- **attack_patterns** (dict, required): Mapping of tactical stages to keyword lists. Example:
  ```python
  {
    "privilege_escalation": ["local", "kernel", "suid", "sudo"],
    "remote_execution": ["remote", "network", "rce", "code execution"]
  }
  ```
- **cve_description** (string, required): CVE description text to classify. Example: `"Local privilege escalation via kernel exploit in Linux 5.x"`
- **pattern_type** (string, required): Tactical stage to match against. Example: `"privilege_escalation"`

## Procedure
1. **Define Tactical Stages**: Map MITRE ATT&CK tactics to keyword lists
2. **Normalize Input**: Convert CVE description to lowercase for case-insensitive matching
3. **Pattern Matching**: Check if any keywords from target tactical stage appear in description
4. **Multi-Label Classification**: A single CVE may match multiple tactical stages
5. **Confidence Scoring**: Count keyword matches to estimate classification confidence
6. **Result Enrichment**: Add MITRE ATT&CK technique IDs and references

## Examples

### Tactical Stage Definitions

**Complete Taxonomy**
```python
attack_patterns = {
    # TA0001 - Initial Access
    "initial_access": [
        "remote", "network", "unauthenticated", "public-facing",
        "phishing", "drive-by", "supply chain", "exploit public"
    ],

    # TA0002 - Execution
    "execution": [
        "code execution", "rce", "command injection", "script",
        "macro", "scheduled task", "user execution"
    ],

    # TA0003 - Persistence
    "persistence": [
        "service", "registry", "scheduled", "startup",
        "boot", "account creation", "web shell", "backdoor"
    ],

    # TA0004 - Privilege Escalation
    "privilege_escalation": [
        "local", "kernel", "suid", "sudo", "setuid",
        "escalation", "elevated", "administrator", "root"
    ],

    # TA0005 - Defense Evasion
    "defense_evasion": [
        "bypass", "obfuscation", "masquerading", "rootkit",
        "disable security", "log deletion", "process injection"
    ],

    # TA0006 - Credential Access
    "credential_access": [
        "password", "credential", "hash", "keylogger",
        "brute force", "credential dump", "authentication"
    ],

    # TA0007 - Discovery
    "discovery": [
        "enumeration", "reconnaissance", "network scan",
        "system information", "account discovery"
    ],

    # TA0008 - Lateral Movement
    "lateral_movement": [
        "smb", "wmi", "ssh", "rdp", "psexec",
        "remote services", "pass the hash", "remote desktop"
    ],

    # TA0009 - Collection
    "collection": [
        "data staged", "clipboard", "screen capture",
        "keylogging", "email collection"
    ],

    # TA0010 - Exfiltration
    "data_exfiltration": [
        "file", "database", "memory", "network",
        "exfiltration", "data transfer", "c2", "command and control"
    ],

    # TA0011 - Impact
    "impact": [
        "denial of service", "dos", "ransomware", "data destruction",
        "defacement", "resource hijacking"
    ]
}
```

### CVE Classification Examples

**Example 1: Privilege Escalation**
```python
cve_description = "Local privilege escalation via SUID binary in Linux kernel 5.10"
matched_patterns = ["privilege_escalation"]  # Keywords: local, suid, kernel
mitre_tactics = ["TA0004"]
confidence = "HIGH"  # 3 keyword matches
```

**Example 2: Multi-Stage Attack**
```python
cve_description = "Remote code execution leading to privilege escalation in Apache 2.4"
matched_patterns = ["execution", "privilege_escalation"]  # Keywords: remote, code execution, escalation
mitre_tactics = ["TA0002", "TA0004"]
confidence = "HIGH"
```

**Example 3: Lateral Movement**
```python
cve_description = "SMB vulnerability allows remote authentication bypass"
matched_patterns = ["lateral_movement", "credential_access"]  # Keywords: smb, remote, authentication
mitre_tactics = ["TA0008", "TA0006"]
confidence = "MEDIUM"
```

### Attack Chain Discovery Workflow

```python
def classify_cve(cve_description, attack_patterns):
    """Classify CVE into tactical stages"""
    description_lower = cve_description.lower()
    matched_stages = []

    for stage, keywords in attack_patterns.items():
        matches = [kw for kw in keywords if kw in description_lower]
        if matches:
            matched_stages.append({
                "stage": stage,
                "matched_keywords": matches,
                "confidence": len(matches)
            })

    return matched_stages

# Example usage
cve = "CVE-2024-1234: Remote code execution via deserialization in Java application"
results = classify_cve(cve, attack_patterns)
# Output: [
#   {"stage": "execution", "matched_keywords": ["remote", "code execution"], "confidence": 2},
#   {"stage": "initial_access", "matched_keywords": ["remote"], "confidence": 1}
# ]
```

### Building Attack Chains

```python
def find_attack_chain(target_software, vulnerabilities, attack_patterns):
    """Find complete attack chains from vulnerability set"""

    # Step 1: Classify all vulnerabilities
    classified_vulns = {}
    for vuln in vulnerabilities:
        stages = classify_cve(vuln['description'], attack_patterns)
        for stage_info in stages:
            stage = stage_info['stage']
            if stage not in classified_vulns:
                classified_vulns[stage] = []
            classified_vulns[stage].append(vuln)

    # Step 2: Build chains following kill chain sequence
    kill_chain_sequence = [
        "initial_access",      # TA0001
        "execution",           # TA0002
        "privilege_escalation",# TA0004
        "persistence",         # TA0003
        "lateral_movement"     # TA0008
    ]

    chains = []
    for initial in classified_vulns.get("initial_access", []):
        chain = {"stages": [{"stage": "initial_access", "vuln": initial}]}

        # Try to extend chain with subsequent stages
        for next_stage in kill_chain_sequence[1:]:
            if next_stage in classified_vulns:
                chain["stages"].append({
                    "stage": next_stage,
                    "vuln": classified_vulns[next_stage][0]
                })

        if len(chain["stages"]) >= 3:  # Minimum viable chain
            chains.append(chain)

    return chains
```

## Indicators / Detection

### Log Sources
- Threat Intelligence Platforms (TIP)
- CVE/NVD databases
- Security Information and Event Management (SIEM)
- Vulnerability scanners

### Detection Patterns

**Splunk Query - Track Attack Chain Coverage**
```spl
index=vuln_intel
| eval stage=case(
    match(description, "(?i)(local|kernel|suid|sudo)"), "privilege_escalation",
    match(description, "(?i)(remote|network|rce)"), "execution",
    match(description, "(?i)(smb|wmi|ssh|rdp)"), "lateral_movement",
    match(description, "(?i)(service|registry|scheduled)"), "persistence",
    1=1, "other"
)
| stats count by stage, cvss_score
| sort -count
```

**Elasticsearch Query - Find Multi-Stage Vulnerabilities**
```json
{
  "query": {
    "bool": {
      "should": [
        {"match": {"description": "remote code execution privilege"}},
        {"match": {"description": "lateral movement persistence"}}
      ],
      "minimum_should_match": 1
    }
  }
}
```

**Python Pattern Matcher**
```python
import re

def detect_attack_stage(cve_text):
    """Detect attack stages in CVE description"""
    patterns = {
        "TA0001": r"\b(remote|unauthenticated|public-facing)\b",
        "TA0004": r"\b(privilege escalation|local|kernel|suid)\b",
        "TA0003": r"\b(persistence|service|registry|startup)\b",
        "TA0008": r"\b(lateral movement|smb|wmi|rdp)\b"
    }

    detected = []
    for tactic_id, pattern in patterns.items():
        if re.search(pattern, cve_text, re.IGNORECASE):
            detected.append(tactic_id)

    return detected
```

## Mitigation Strategies

### Defensive Prioritization by Stage

**High Priority (Break the Chain Early)**
1. **Initial Access (TA0001)**: Patch internet-facing vulnerabilities first
   - Web application vulnerabilities
   - VPN/Remote access vulnerabilities
   - Public-facing services

2. **Privilege Escalation (TA0004)**: Prevent lateral privilege gains
   - Kernel vulnerabilities
   - SUID/sudo misconfigurations
   - Service account vulnerabilities

**Medium Priority (Limit Impact)**
3. **Lateral Movement (TA0008)**: Contain breaches
   - Network segmentation
   - Credential protection (disable NTLM, enforce Kerberos)
   - Monitor SMB/RDP traffic

4. **Persistence (TA0003)**: Detect long-term compromise
   - Monitor service creation
   - Registry monitoring
   - Scheduled task auditing

### Defense-in-Depth Mapping

```yaml
attack_stage: privilege_escalation
defensive_controls:
  - preventive:
      - Least privilege enforcement
      - Kernel hardening (SELinux, AppArmor)
      - Disable unnecessary SUID binaries
  - detective:
      - Monitor for suspicious privilege changes
      - Audit sudo usage
      - Kernel exploit detection (LKRG)
  - responsive:
      - Automated privilege revocation
      - Isolate compromised accounts
      - Incident response playbook activation
```

## Limitations and Caveats

- **Keyword Ambiguity**: Terms like "remote" or "service" may appear in non-security contexts
- **False Negatives**: Novel attack techniques may not match existing keywords
- **Language Dependency**: Primarily designed for English CVE descriptions
- **Taxonomy Drift**: Requires updates as MITRE ATT&CK evolves
- **Context Loss**: Simple keyword matching ignores semantic context
- **Multi-Label Complexity**: Single vulnerability may enable multiple tactics
- **Confidence Scoring**: More keyword matches ≠ higher actual relevance
- **Zero-Day Gaps**: Emerging threats may lack descriptive keywords

## Source Excerpts

### [S1] Attack Pattern Taxonomy Definition
```python
# From vul_correlators.py lines 10-16
self.attack_patterns = {
    "privilege_escalation": ["local", "kernel", "suid", "sudo"],
    "remote_execution": ["remote", "network", "rce", "code execution"],
    "persistence": ["service", "registry", "scheduled", "startup"],
    "lateral_movement": ["smb", "wmi", "ssh", "rdp"],
    "data_exfiltration": ["file", "database", "memory", "network"]
}
```

## References
- **MITRE ATT&CK Framework** - https://attack.mitre.org/
- **MITRE ATT&CK Tactics** - https://attack.mitre.org/tactics/enterprise/
- **Lockheed Martin Cyber Kill Chain** - https://www.lockheedmartin.com/en-us/capabilities/cyber/cyber-kill-chain.html
- **NIST SP 800-61 Rev. 2: Computer Security Incident Handling Guide** - https://csrc.nist.gov/publications/detail/sp/800-61/rev-2/final
- **CVE Program** - https://www.cve.org/
- **NVD - National Vulnerability Database** - https://nvd.nist.gov/
