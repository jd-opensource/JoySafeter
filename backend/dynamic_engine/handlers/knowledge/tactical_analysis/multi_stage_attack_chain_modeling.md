# Multi-Stage Attack Chain Modeling

## Overview
- **Purpose**: Discover and evaluate viable multi-stage attack chains by linking vulnerabilities across MITRE ATT&CK tactical stages with probabilistic success scoring
- **Category**: tactical_analysis
- **Severity**: medium
- **Tags**: attack-chain, kill-chain, threat-modeling, risk-assessment, attack-path, red-team-planning, TA0001, TA0004, TA0003

## Context and Use-Cases
- **Red Team Planning**: Identify complete attack paths from initial access to objectives (data exfiltration, persistence)
- **Threat Modeling**: Assess which attack chains are most viable against specific targets
- **Risk Prioritization**: Focus patching on vulnerabilities that enable high-probability attack chains
- **Purple Team Exercises**: Test detection coverage across multi-stage attack scenarios
- **Security Architecture**: Design defenses that break attack chains at critical junctures
- **Incident Response**: Predict attacker next moves based on current stage in kill chain

## Key Parameters and Inputs
- **target_software** (string, required): Primary target software/platform. Example: `"Windows Server 2019"`
- **max_depth** (integer, optional): Maximum attack chain length. Default: `3`. Example: `5`
- **vulnerability_database** (list, required): Available vulnerabilities with metadata. Example:
  ```python
  [
    {"cve_id": "CVE-2024-1234", "cvss_score": 9.8, "exploitability": "HIGH", "stage": "initial_access"},
    {"cve_id": "CVE-2024-5678", "cvss_score": 7.8, "exploitability": "MEDIUM", "stage": "privilege_escalation"}
  ]
  ```
- **success_probabilities** (dict, optional): Stage-specific success probability estimates. Example:
  ```python
  {
    "initial_access": 0.75,
    "privilege_escalation": 0.60,
    "persistence": 0.80
  }
  ```

## Procedure
1. **Classify Vulnerabilities**: Use attack pattern taxonomy to categorize vulnerabilities by tactical stage
2. **Identify Initial Access**: Find vulnerabilities enabling initial compromise (remote execution, authentication bypass)
3. **Build Chain Stages**: For each initial access vulnerability, attempt to extend chain with subsequent stages:
   - Stage 1: Initial Access (TA0001)
   - Stage 2: Privilege Escalation (TA0004)
   - Stage 3: Persistence (TA0003)
   - Stage 4: Lateral Movement (TA0008) [optional]
   - Stage 5: Data Exfiltration (TA0010) [optional]
4. **Calculate Chain Probability**: Multiply individual stage success probabilities
5. **Rank Chains**: Sort by overall probability and complexity
6. **Generate Recommendations**: Provide actionable guidance for red/blue teams

## Examples

### Complete Attack Chain Discovery

```python
def find_attack_chains(target_software, vulnerabilities, max_depth=3):
    """
    Discover multi-stage attack chains for target software

    Args:
        target_software: Target platform/application
        vulnerabilities: List of available vulnerabilities
        max_depth: Maximum chain length

    Returns:
        Dictionary with discovered chains and recommendations
    """

    # Step 1: Classify vulnerabilities by stage
    classified_vulns = classify_vulnerabilities(vulnerabilities)

    # Step 2: Define kill chain sequence
    kill_chain_sequence = [
        "initial_access",       # TA0001
        "execution",            # TA0002
        "privilege_escalation", # TA0004
        "persistence",          # TA0003
        "lateral_movement",     # TA0008
        "data_exfiltration"     # TA0010
    ]

    # Step 3: Build chains starting from initial access
    chains = []

    for initial_vuln in classified_vulns.get("initial_access", [])[:5]:  # Limit for performance
        chain = {
            "chain_id": f"chain_{len(chains) + 1}",
            "target": target_software,
            "stages": [
                {
                    "stage": 1,
                    "tactic": "Initial Access",
                    "tactic_id": "TA0001",
                    "vulnerability": initial_vuln,
                    "success_probability": calculate_stage_probability(initial_vuln),
                    "techniques": ["T1190", "T1133"]  # Exploit Public-Facing App, External Remote Services
                }
            ],
            "overall_probability": calculate_stage_probability(initial_vuln),
            "complexity": "LOW"
        }

        # Step 4: Extend chain with subsequent stages
        current_probability = chain["overall_probability"]

        for stage_idx, stage_name in enumerate(kill_chain_sequence[1:max_depth], start=2):
            if stage_name in classified_vulns and classified_vulns[stage_name]:
                next_vuln = select_best_vulnerability(classified_vulns[stage_name])
                stage_prob = calculate_stage_probability(next_vuln)

                chain["stages"].append({
                    "stage": stage_idx,
                    "tactic": stage_name.replace("_", " ").title(),
                    "tactic_id": get_mitre_tactic_id(stage_name),
                    "vulnerability": next_vuln,
                    "success_probability": stage_prob,
                    "techniques": get_mitre_techniques(stage_name)
                })

                current_probability *= stage_prob
                chain["overall_probability"] = current_probability

        # Step 5: Calculate complexity
        chain["complexity"] = calculate_complexity(chain)

        # Only include chains with minimum viable length
        if len(chain["stages"]) >= 2:
            chains.append(chain)

    # Step 6: Rank chains
    chains.sort(key=lambda x: x["overall_probability"], reverse=True)

    return {
        "success": True,
        "target_software": target_software,
        "total_chains": len(chains),
        "attack_chains": chains,
        "recommendations": generate_recommendations(chains)
    }


def calculate_stage_probability(vulnerability):
    """Calculate success probability for a vulnerability"""
    # Based on CVSS exploitability metrics
    exploitability_map = {
        "HIGH": 0.85,
        "MEDIUM": 0.60,
        "LOW": 0.35
    }

    base_prob = exploitability_map.get(vulnerability.get("exploitability", "MEDIUM"), 0.60)

    # Adjust based on CVSS score
    cvss_score = vulnerability.get("cvss_score", 5.0)
    if cvss_score >= 9.0:
        base_prob *= 1.1  # Critical vulnerabilities slightly easier
    elif cvss_score < 4.0:
        base_prob *= 0.8  # Low severity harder to exploit

    return min(base_prob, 0.95)  # Cap at 95%


def calculate_complexity(chain):
    """Determine attack chain complexity"""
    num_stages = len(chain["stages"])
    avg_probability = chain["overall_probability"] ** (1/num_stages)

    if num_stages <= 2 and avg_probability > 0.7:
        return "LOW"
    elif num_stages <= 3 and avg_probability > 0.5:
        return "MEDIUM"
    else:
        return "HIGH"


def get_mitre_tactic_id(stage_name):
    """Map stage name to MITRE ATT&CK tactic ID"""
    tactic_mapping = {
        "initial_access": "TA0001",
        "execution": "TA0002",
        "persistence": "TA0003",
        "privilege_escalation": "TA0004",
        "defense_evasion": "TA0005",
        "credential_access": "TA0006",
        "discovery": "TA0007",
        "lateral_movement": "TA0008",
        "collection": "TA0009",
        "data_exfiltration": "TA0010",
        "impact": "TA0011"
    }
    return tactic_mapping.get(stage_name, "TA0000")
```

### Example Output

```json
{
  "success": true,
  "target_software": "Windows Server 2019",
  "total_chains": 3,
  "attack_chains": [
    {
      "chain_id": "chain_1",
      "target": "Windows Server 2019",
      "stages": [
        {
          "stage": 1,
          "tactic": "Initial Access",
          "tactic_id": "TA0001",
          "vulnerability": {
            "cve_id": "CVE-2024-1234",
            "description": "Remote code execution in IIS",
            "cvss_score": 9.8,
            "exploitability": "HIGH"
          },
          "success_probability": 0.85,
          "techniques": ["T1190"]
        },
        {
          "stage": 2,
          "tactic": "Privilege Escalation",
          "tactic_id": "TA0004",
          "vulnerability": {
            "cve_id": "CVE-2024-5678",
            "description": "Local privilege escalation via kernel exploit",
            "cvss_score": 7.8,
            "exploitability": "MEDIUM"
          },
          "success_probability": 0.60,
          "techniques": ["T1068"]
        },
        {
          "stage": 3,
          "tactic": "Persistence",
          "tactic_id": "TA0003",
          "vulnerability": {
            "cve_id": "CVE-2024-9012",
            "description": "Service creation without authentication",
            "cvss_score": 6.5,
            "exploitability": "HIGH"
          },
          "success_probability": 0.80,
          "techniques": ["T1543.003"]
        }
      ],
      "overall_probability": 0.408,
      "complexity": "MEDIUM"
    }
  ],
  "recommendations": {
    "summary": "Found 3 viable attack chains with probabilities ranging from 40.8% to 15.2%",
    "highest_risk_chain": "chain_1 (40.8% success probability)",
    "critical_vulnerabilities": ["CVE-2024-1234", "CVE-2024-5678"],
    "defensive_priorities": [
      "Patch CVE-2024-1234 (Initial Access) to break all chains",
      "Harden privilege escalation paths (kernel hardening, LAPS)",
      "Monitor for sequential attack patterns in SIEM"
    ]
  }
}
```

### Red Team Attack Chain Planning

```python
# Scenario: Planning attack against web application infrastructure

target = "LAMP Stack (Linux + Apache + MySQL + PHP)"

# Available vulnerabilities from reconnaissance
vulnerabilities = [
    {
        "cve_id": "CVE-2024-APACHE",
        "description": "Apache mod_cgi RCE",
        "cvss_score": 9.8,
        "exploitability": "HIGH",
        "stage": "initial_access"
    },
    {
        "cve_id": "CVE-2024-KERNEL",
        "description": "Linux kernel privilege escalation",
        "cvss_score": 7.8,
        "exploitability": "MEDIUM",
        "stage": "privilege_escalation"
    },
    {
        "cve_id": "CVE-2024-MYSQL",
        "description": "MySQL UDF privilege escalation",
        "cvss_score": 8.8,
        "exploitability": "HIGH",
        "stage": "privilege_escalation"
    },
    {
        "cve_id": "CVE-2024-CRON",
        "description": "Cron job hijacking for persistence",
        "cvss_score": 6.0,
        "exploitability": "MEDIUM",
        "stage": "persistence"
    }
]

# Discover attack chains
result = find_attack_chains(target, vulnerabilities, max_depth=4)

# Red team can now:
# 1. Select highest probability chain (chain_1: 40.8%)
# 2. Prepare exploits for each stage
# 3. Plan fallback options if a stage fails
# 4. Estimate time/resources needed
```

### Blue Team Defense Planning

```python
def prioritize_defenses(attack_chains):
    """
    Prioritize defensive controls based on attack chain analysis

    Strategy: Break chains at stages with highest impact/cost ratio
    """

    # Calculate impact of patching each vulnerability
    vuln_impact = {}

    for chain in attack_chains:
        for stage in chain["stages"]:
            cve_id = stage["vulnerability"]["cve_id"]

            if cve_id not in vuln_impact:
                vuln_impact[cve_id] = {
                    "chains_broken": 0,
                    "total_probability_reduced": 0.0,
                    "stage": stage["tactic"],
                    "cvss": stage["vulnerability"]["cvss_score"]
                }

            vuln_impact[cve_id]["chains_broken"] += 1
            vuln_impact[cve_id]["total_probability_reduced"] += chain["overall_probability"]

    # Rank by impact
    ranked_vulns = sorted(
        vuln_impact.items(),
        key=lambda x: (x[1]["chains_broken"], x[1]["total_probability_reduced"]),
        reverse=True
    )

    return {
        "priority_1_critical": [v[0] for v in ranked_vulns[:3]],
        "priority_2_high": [v[0] for v in ranked_vulns[3:6]],
        "priority_3_medium": [v[0] for v in ranked_vulns[6:]],
        "rationale": "Patching priority_1 vulnerabilities breaks the most attack chains"
    }

# Example output:
# {
#   "priority_1_critical": ["CVE-2024-1234", "CVE-2024-5678"],
#   "priority_2_high": ["CVE-2024-9012"],
#   "rationale": "Patching CVE-2024-1234 breaks all 3 attack chains at initial access stage"
# }
```

### Probability Calculation Examples

**Independent Stage Probabilities**
```python
# Chain: Initial Access (85%) → Privilege Escalation (60%) → Persistence (80%)
overall_probability = 0.85 * 0.60 * 0.80 = 0.408 (40.8%)

# Interpretation: 40.8% chance of successfully completing entire chain
```

**Impact of Patching**
```python
# Before patching
chain_probability = 0.85 * 0.60 * 0.80 = 0.408

# After patching privilege escalation vulnerability
chain_probability = 0.85 * 0.0 * 0.80 = 0.0  # Chain broken

# After hardening (reducing stage probability)
chain_probability = 0.85 * 0.30 * 0.80 = 0.204  # 50% risk reduction
```

## Indicators / Detection

### Log Sources
- SIEM (Security Information and Event Management)
- EDR (Endpoint Detection and Response)
- Network Traffic Analysis
- Application Logs

### Detection Patterns

**Splunk - Sequential Attack Stage Detection**
```spl
index=security_events
| eval stage=case(
    match(event_type, "exploit|rce|injection"), "initial_access",
    match(event_type, "privilege_escalation|sudo|kernel"), "privilege_escalation",
    match(event_type, "persistence|service_creation|scheduled_task"), "persistence",
    match(event_type, "lateral_movement|smb|rdp"), "lateral_movement",
    1=1, "other"
)
| transaction src_ip maxspan=4h
| where mvcount(stage) >= 3
| stats values(stage) as attack_chain, values(event_type) as events by src_ip
| where match(attack_chain, "initial_access.*privilege_escalation.*persistence")
```

**Sigma Rule - Multi-Stage Attack Chain**
```yaml
title: Multi-Stage Attack Chain Detected
logsource:
  category: security_events
detection:
  initial_access:
    event_type:
      - exploit
      - rce
      - authentication_bypass
  privilege_escalation:
    event_type:
      - privilege_escalation
      - kernel_exploit
      - sudo_abuse
  persistence:
    event_type:
      - service_creation
      - scheduled_task
      - registry_modification
  timeframe: 4h
  condition: initial_access followed by privilege_escalation followed by persistence
level: high
```

**Python - Attack Chain Correlation**
```python
def detect_attack_chain(events, time_window_hours=4):
    """Correlate events to detect multi-stage attacks"""
    from datetime import datetime, timedelta

    # Group events by source IP
    events_by_ip = {}
    for event in events:
        ip = event['src_ip']
        if ip not in events_by_ip:
            events_by_ip[ip] = []
        events_by_ip[ip].append(event)

    # Detect chains
    detected_chains = []

    for ip, ip_events in events_by_ip.items():
        # Sort by timestamp
        ip_events.sort(key=lambda x: x['timestamp'])

        # Look for stage progression
        stages_seen = []
        chain_start = None

        for event in ip_events:
            stage = classify_event_stage(event)

            if stage == "initial_access" and not chain_start:
                chain_start = event['timestamp']
                stages_seen = [stage]
            elif chain_start:
                time_diff = event['timestamp'] - chain_start
                if time_diff <= timedelta(hours=time_window_hours):
                    if stage not in stages_seen:
                        stages_seen.append(stage)

        # Alert if multi-stage chain detected
        if len(stages_seen) >= 3:
            detected_chains.append({
                "src_ip": ip,
                "stages": stages_seen,
                "duration": time_diff,
                "severity": "HIGH"
            })

    return detected_chains
```

## Mitigation Strategies

### Break Chains at Critical Stages

**Priority 1: Initial Access Prevention**
- Patch internet-facing vulnerabilities immediately
- Implement Web Application Firewall (WAF)
- Network segmentation (DMZ isolation)
- Multi-factor authentication for remote access

**Priority 2: Privilege Escalation Prevention**
- Kernel hardening (SELinux, AppArmor)
- Disable unnecessary SUID binaries
- Implement LAPS for local admin passwords
- Regular privilege audits

**Priority 3: Persistence Detection**
- File integrity monitoring
- Service creation monitoring
- Registry monitoring (Windows)
- Cron/systemd monitoring (Linux)

### Defense-in-Depth by Stage

```yaml
stage: initial_access
controls:
  preventive:
    - WAF with OWASP ModSecurity CRS
    - Network firewall rules (whitelist only)
    - Input validation and sanitization
  detective:
    - IDS/IPS signatures for known exploits
    - Anomaly detection on web traffic
    - Failed authentication monitoring
  responsive:
    - Automatic IP blocking after threshold
    - Incident response playbook activation
    - Forensic data collection

stage: privilege_escalation
controls:
  preventive:
    - Principle of least privilege
    - Kernel exploit mitigations (KASLR, SMEP)
    - Disable dangerous sudo configurations
  detective:
    - EDR monitoring for privilege changes
    - Audit logs for sudo/su usage
    - Kernel exploit detection (LKRG)
  responsive:
    - Automatic privilege revocation
    - Account lockout
    - Isolate affected systems

stage: persistence
controls:
  preventive:
    - Immutable system files
    - Disable unnecessary startup locations
    - Code signing enforcement
  detective:
    - File integrity monitoring (AIDE, Tripwire)
    - Service creation alerts
    - Scheduled task monitoring
  responsive:
    - Remove malicious persistence
    - Rebuild from known-good image
    - Hunt for additional persistence mechanisms
```

### Reduce Chain Probability Through Patching

```python
# Patching strategy based on chain impact
def calculate_patching_impact(chains, vulnerability_to_patch):
    """Calculate risk reduction from patching a vulnerability"""

    total_risk_before = sum(chain["overall_probability"] for chain in chains)

    # Remove chains that use this vulnerability
    remaining_chains = [
        chain for chain in chains
        if not any(
            stage["vulnerability"]["cve_id"] == vulnerability_to_patch
            for stage in chain["stages"]
        )
    ]

    total_risk_after = sum(chain["overall_probability"] for chain in remaining_chains)

    risk_reduction = total_risk_before - total_risk_after
    risk_reduction_percent = (risk_reduction / total_risk_before) * 100

    return {
        "vulnerability": vulnerability_to_patch,
        "chains_broken": len(chains) - len(remaining_chains),
        "risk_reduction": risk_reduction,
        "risk_reduction_percent": f"{risk_reduction_percent:.1f}%",
        "remaining_risk": total_risk_after
    }
```

## Limitations and Caveats

- **Probability Estimates**: Success probabilities are heuristic, not empirically validated
- **Independence Assumption**: Assumes stage probabilities are independent (may not be true)
- **Static Analysis**: Does not account for dynamic defender actions or detection
- **Known Vulnerabilities Only**: Limited to vulnerabilities in database (misses zero-days)
- **Simplified Model**: Real attacks may involve parallel paths, retries, and adaptation
- **No Detection Probability**: Does not model likelihood of detection at each stage
- **Resource Constraints**: Does not account for attacker skill, time, or tool availability
- **Environmental Factors**: Network topology, security controls, and monitoring affect real probability
- **Complexity Calculation**: Simplified complexity metric may not reflect operational difficulty

## Source Excerpts

### [S1] Attack Chain Discovery Logic
```python
# From vul_correlators.py lines 25-89
def find_attack_chains(self, target_software, max_depth=3):
    """Find multi-vulnerability attack chains"""
    try:
        chains = []
        base_software = target_software.lower()

        # Find initial access vulnerabilities
        initial_vulns = self._find_vulnerabilities_by_pattern(base_software, "remote_execution")

        for initial_vuln in initial_vulns[:3]:
            chain = {
                "chain_id": f"chain_{len(chains) + 1}",
                "target": target_software,
                "stages": [
                    {
                        "stage": 1,
                        "objective": "Initial Access",
                        "vulnerability": initial_vuln,
                        "success_probability": 0.75
                    }
                ],
                "overall_probability": 0.75,
                "complexity": "MEDIUM"
            }

            # Find privilege escalation
            priv_esc_vulns = self._find_vulnerabilities_by_pattern(base_software, "privilege_escalation")
            if priv_esc_vulns:
                chain["stages"].append({
                    "stage": 2,
                    "objective": "Privilege Escalation",
                    "vulnerability": priv_esc_vulns[0],
                    "success_probability": 0.60
                })
                chain["overall_probability"] *= 0.60

            chains.append(chain)

        return {
            "success": True,
            "target_software": target_software,
            "total_chains": len(chains),
            "attack_chains": chains
        }
```

### [S2] Probability Calculation
```python
# From vul_correlators.py lines 48-64
{
    "stage": 1,
    "objective": "Initial Access",
    "vulnerability": initial_vuln,
    "success_probability": 0.75
}

# Multiplicative probability for chain
chain["overall_probability"] *= 0.60  # Stage 2 probability
chain["overall_probability"] *= 0.80  # Stage 3 probability

# Final: 0.75 * 0.60 * 0.80 = 0.36 (36% overall success)
```

### [S3] Recommendation Generation
```python
# From vul_correlators.py lines 112-126
def _generate_chain_recommendations(self, chains):
    """Generate recommendations for attack chains"""
    if not chains:
        return "No viable attack chains found for target"

    recommendations = [
        f"Found {len(chains)} potential attack chains",
        f"Highest probability chain: {max(chains, key=lambda x: x['overall_probability'])['overall_probability']:.2%}",
        "Recommendations:",
        "- Test chains in order of probability",
        "- Prepare fallback methods for each stage",
        "- Consider detection evasion at each stage"
    ]

    return "\n".join(recommendations)
```

## References
- **MITRE ATT&CK Framework** - https://attack.mitre.org/
- **Lockheed Martin Cyber Kill Chain** - https://www.lockheedmartin.com/en-us/capabilities/cyber/cyber-kill-chain.html
- **NIST SP 800-30 Rev. 1 - Guide for Conducting Risk Assessments** - https://csrc.nist.gov/publications/detail/sp/800-30/rev-1/final
- **Attack Trees (Bruce Schneier)** - https://www.schneier.com/academic/archives/1999/12/attack_trees.html
- **CVSS v3.1 Specification** - https://www.first.org/cvss/v3.1/specification-document
- **Threat Modeling: Designing for Security (Adam Shostack)** - https://www.threatmodelingbook.com/
