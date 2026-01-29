# Software Ecosystem Relationships

## Overview
- **Purpose**: Map software dependencies and co-deployment patterns to identify attack surface expansion, lateral movement paths, and vulnerability propagation chains
- **Category**: tactical_analysis
- **Severity**: info
- **Tags**: attack-surface, lateral-movement, dependency-analysis, asset-correlation, supply-chain, T1210, T1021

## Context and Use-Cases
- **Lateral Movement Planning**: Identify which systems are likely reachable after compromising a specific software stack
- **Attack Surface Mapping**: Understand that compromising IIS likely means Windows Server, Office, and potentially Exchange are present
- **Vulnerability Impact Assessment**: When a PHP vulnerability is disclosed, know that Apache/Nginx and MySQL/PostgreSQL are likely also present
- **Red Team Reconnaissance**: Fingerprint one service to infer presence of related technologies
- **Blue Team Defense Planning**: Segment networks based on ecosystem boundaries (Windows vs Linux vs Database tiers)
- **Supply Chain Risk**: Understand cascading impact when a core ecosystem component is compromised

## Key Parameters and Inputs
- **software_relationships** (dict, required): Mapping of platform/technology to commonly co-deployed software. Example:
  ```python
  {
    "windows": ["iis", "office", "exchange", "sharepoint"],
    "linux": ["apache", "nginx", "mysql", "postgresql"]
  }
  ```
- **primary_software** (string, required): Initial compromised or identified software. Example: `"iis"`
- **ecosystem_type** (string, required): Platform category. Example: `"windows"`

## Procedure
1. **Fingerprint Initial Software**: Identify primary software through banner grabbing, service detection, or exploitation
2. **Lookup Ecosystem**: Determine which ecosystem the software belongs to (Windows, Linux, Web, Database)
3. **Enumerate Related Software**: Query relationship map for likely co-deployed technologies
4. **Prioritize Targets**: Rank related software by likelihood and attack value
5. **Validate Presence**: Confirm suspected software through active scanning or passive analysis
6. **Plan Lateral Movement**: Design attack path leveraging ecosystem relationships

## Examples

### Extended Ecosystem Mapping

```python
software_relationships = {
    # Operating System Ecosystems
    "windows": {
        "core": ["active_directory", "smb", "rdp", "wmi", "powershell"],
        "web": ["iis", "asp.net", "mssql"],
        "productivity": ["office", "exchange", "sharepoint", "teams"],
        "management": ["sccm", "wsus", "group_policy"]
    },

    "linux": {
        "core": ["ssh", "systemd", "bash", "cron"],
        "web": ["apache", "nginx", "php", "python", "nodejs"],
        "database": ["mysql", "postgresql", "mongodb", "redis"],
        "container": ["docker", "kubernetes", "containerd"]
    },

    # Web Application Stacks
    "lamp_stack": ["linux", "apache", "mysql", "php"],
    "lemp_stack": ["linux", "nginx", "mysql", "php"],
    "mean_stack": ["mongodb", "express", "angular", "nodejs"],
    "mern_stack": ["mongodb", "express", "react", "nodejs"],

    # Enterprise Stacks
    "microsoft_365": ["exchange_online", "sharepoint_online", "teams", "onedrive", "azure_ad"],
    "aws_web": ["ec2", "rds", "s3", "cloudfront", "route53", "elb"],
    "kubernetes_stack": ["etcd", "kube-apiserver", "kubelet", "docker", "helm"],

    # Database Ecosystems
    "mysql_ecosystem": ["phpmyadmin", "mysql_workbench", "percona", "mariadb"],
    "postgresql_ecosystem": ["pgadmin", "postgrest", "timescaledb"],
    "mssql_ecosystem": ["ssms", "ssis", "ssrs", "ssas"],

    # Development Stacks
    "java_stack": ["tomcat", "spring", "maven", "jenkins"],
    "python_stack": ["django", "flask", "celery", "gunicorn", "nginx"],
    "ruby_stack": ["rails", "puma", "sidekiq", "redis"],

    # Cloud Native
    "docker_stack": ["docker", "docker-compose", "portainer", "registry"],
    "ci_cd": ["jenkins", "gitlab", "github_actions", "artifactory"]
}
```

### Attack Surface Expansion Example

**Scenario: IIS Web Server Compromised**

```python
def analyze_attack_surface(compromised_software):
    """Analyze attack surface after initial compromise"""

    # Step 1: Identify ecosystem
    if compromised_software == "iis":
        ecosystem = "windows"

        # Step 2: Enumerate likely co-deployed software
        likely_present = {
            "high_confidence": [
                "smb",           # File sharing (always present on Windows)
                "rdp",           # Remote desktop (very common)
                "active_directory"  # If domain-joined (80% probability)
            ],
            "medium_confidence": [
                "mssql",         # Database for web apps (60% probability)
                "exchange",      # Email server (40% in enterprises)
                "sharepoint"     # Collaboration (30% in enterprises)
            ],
            "low_confidence": [
                "sccm",          # Systems management (20% probability)
                "office"         # Desktop apps (varies by server role)
            ]
        }

        # Step 3: Identify lateral movement paths
        lateral_movement_paths = [
            {
                "target": "smb",
                "technique": "T1021.002 - SMB/Windows Admin Shares",
                "requirements": ["admin credentials", "network access"],
                "tools": ["psexec", "impacket"]
            },
            {
                "target": "rdp",
                "technique": "T1021.001 - Remote Desktop Protocol",
                "requirements": ["user credentials", "rdp enabled"],
                "tools": ["rdesktop", "xfreerdp"]
            },
            {
                "target": "active_directory",
                "technique": "T1078 - Valid Accounts",
                "requirements": ["domain credentials", "domain trust"],
                "tools": ["mimikatz", "bloodhound"]
            }
        ]

        return {
            "ecosystem": ecosystem,
            "likely_software": likely_present,
            "lateral_movement": lateral_movement_paths
        }
```

**Output:**
```json
{
  "ecosystem": "windows",
  "likely_software": {
    "high_confidence": ["smb", "rdp", "active_directory"],
    "medium_confidence": ["mssql", "exchange", "sharepoint"],
    "low_confidence": ["sccm", "office"]
  },
  "lateral_movement": [
    {
      "target": "smb",
      "technique": "T1021.002",
      "requirements": ["admin credentials", "network access"],
      "tools": ["psexec", "impacket"]
    }
  ]
}
```

### Lateral Movement Path Discovery

```python
def find_lateral_movement_paths(source_ecosystem, target_ecosystem):
    """Find lateral movement paths between ecosystems"""

    cross_ecosystem_bridges = {
        ("windows", "linux"): [
            {"protocol": "ssh", "requirement": "SSH server on Linux, SSH client on Windows"},
            {"protocol": "smb", "requirement": "Samba on Linux"},
            {"protocol": "http/https", "requirement": "Web services"}
        ],
        ("linux", "windows"): [
            {"protocol": "rdp", "requirement": "RDP client on Linux (xfreerdp)"},
            {"protocol": "smb", "requirement": "SMB client on Linux (smbclient)"},
            {"protocol": "winrm", "requirement": "WinRM enabled on Windows"}
        ],
        ("web", "database"): [
            {"protocol": "mysql", "requirement": "Database credentials from web config"},
            {"protocol": "postgresql", "requirement": "Connection string in application"},
            {"protocol": "mssql", "requirement": "Integrated authentication"}
        ]
    }

    return cross_ecosystem_bridges.get((source_ecosystem, target_ecosystem), [])

# Example usage
paths = find_lateral_movement_paths("windows", "linux")
# Returns: [
#   {"protocol": "ssh", "requirement": "SSH server on Linux, SSH client on Windows"},
#   {"protocol": "smb", "requirement": "Samba on Linux"},
#   {"protocol": "http/https", "requirement": "Web services"}
# ]
```

### Vulnerability Propagation Analysis

```python
def assess_vulnerability_impact(vulnerable_software, software_relationships):
    """Assess cascading impact of vulnerability in ecosystem"""

    # Example: Apache Log4j vulnerability
    if vulnerable_software == "log4j":
        affected_ecosystem = [
            "java_stack",      # Direct dependency
            "elasticsearch",   # Uses Log4j
            "kafka",          # Uses Log4j
            "hadoop",         # Uses Log4j
            "tomcat",         # May use Log4j
            "spring"          # May use Log4j
        ]

        impact_assessment = {
            "direct_impact": "Remote Code Execution in Java applications",
            "affected_software": affected_ecosystem,
            "lateral_movement_risk": "HIGH - Can pivot to all Java services",
            "recommended_actions": [
                "Scan for Log4j usage across all Java applications",
                "Patch or mitigate (disable JNDI lookups)",
                "Monitor for exploitation attempts",
                "Segment Java application network"
            ]
        }

        return impact_assessment
```

### Red Team Reconnaissance Workflow

```bash
# Step 1: Fingerprint web server
nmap -sV -p 80,443 target.com
# Output: 80/tcp open http Microsoft IIS httpd 10.0

# Step 2: Infer ecosystem
# IIS detected → Windows ecosystem likely

# Step 3: Enumerate related services
nmap -sV -p 445,3389,1433,5985 target.com
# 445/tcp  open  microsoft-ds   (SMB - confirmed)
# 3389/tcp open  ms-wbt-server  (RDP - confirmed)
# 1433/tcp open  ms-sql-s       (MSSQL - confirmed)
# 5985/tcp open  wsman          (WinRM - confirmed)

# Step 4: Plan lateral movement
# - Exploit IIS for initial access
# - Dump credentials from IIS application pool
# - Use credentials for SMB lateral movement
# - Escalate via MSSQL xp_cmdshell
# - Persist via WinRM scheduled tasks
```

## Indicators / Detection

### Log Sources
- Asset Management Database (CMDB)
- Network Traffic Analysis (NTA)
- Service Discovery Logs
- Configuration Management Systems

### Detection Patterns

**Splunk - Detect Lateral Movement Within Ecosystem**
```spl
index=network_traffic
| eval src_ecosystem=case(
    match(src_software, "iis|exchange|sharepoint"), "windows",
    match(src_software, "apache|nginx|php"), "linux",
    1=1, "unknown"
)
| eval dst_ecosystem=case(
    match(dst_software, "iis|exchange|sharepoint"), "windows",
    match(dst_software, "apache|nginx|php"), "linux",
    1=1, "unknown"
)
| where src_ecosystem=dst_ecosystem AND protocol IN ("smb", "rdp", "ssh")
| stats count by src_host, dst_host, protocol, src_ecosystem
| where count > threshold
```

**Sigma Rule - Cross-Ecosystem Authentication**
```yaml
title: Cross-Ecosystem Authentication Attempt
logsource:
  category: authentication
detection:
  selection:
    source_os: windows
    target_os: linux
    protocol: ssh
  condition: selection
level: medium
```

**Python - Map Asset Relationships**
```python
def map_asset_relationships(asset_inventory):
    """Build relationship graph from asset inventory"""
    import networkx as nx

    G = nx.Graph()

    for asset in asset_inventory:
        # Add node with ecosystem attribute
        ecosystem = determine_ecosystem(asset['software'])
        G.add_node(asset['hostname'], ecosystem=ecosystem, software=asset['software'])

        # Add edges for network connections
        for connection in asset['connections']:
            G.add_edge(asset['hostname'], connection['target'])

    # Find cross-ecosystem connections (potential lateral movement paths)
    cross_ecosystem_edges = [
        (u, v) for u, v in G.edges()
        if G.nodes[u]['ecosystem'] != G.nodes[v]['ecosystem']
    ]

    return G, cross_ecosystem_edges
```

## Mitigation Strategies

### Network Segmentation by Ecosystem

```yaml
# Firewall Rules Example
segments:
  - name: windows_tier
    allowed_inbound:
      - source: dmz
        protocol: https
        port: 443
    allowed_outbound:
      - destination: database_tier
        protocol: mssql
        port: 1433
    blocked:
      - destination: linux_tier  # Prevent cross-ecosystem lateral movement

  - name: linux_tier
    allowed_inbound:
      - source: dmz
        protocol: https
        port: 443
    allowed_outbound:
      - destination: database_tier
        protocol: mysql
        port: 3306
    blocked:
      - destination: windows_tier
```

### Ecosystem-Specific Hardening

**Windows Ecosystem**
- Disable SMBv1
- Require SMB signing
- Enable Credential Guard
- Implement LAPS for local admin passwords
- Use tiered admin model (separate admin accounts per tier)

**Linux Ecosystem**
- Disable SSH password authentication (key-only)
- Implement SELinux/AppArmor
- Use sudo with logging
- Separate service accounts per application
- Implement file integrity monitoring

**Database Ecosystem**
- Network-level isolation (private subnet)
- Require encrypted connections (TLS)
- Principle of least privilege for database accounts
- Audit all privileged operations
- Disable xp_cmdshell and similar dangerous features

### Monitoring Cross-Ecosystem Activity

```python
# Alert on unusual cross-ecosystem authentication
alert_rules = [
    {
        "name": "Windows to Linux SSH",
        "condition": "source_os=windows AND protocol=ssh AND target_os=linux",
        "severity": "MEDIUM",
        "action": "Alert security team"
    },
    {
        "name": "Linux to Windows RDP",
        "condition": "source_os=linux AND protocol=rdp AND target_os=windows",
        "severity": "HIGH",
        "action": "Block and alert"
    },
    {
        "name": "Web to Database Direct Access",
        "condition": "source_tier=web AND target_tier=database AND NOT via_app_server",
        "severity": "HIGH",
        "action": "Block and investigate"
    }
]
```

## Limitations and Caveats

- **Static Mapping**: Real deployments may differ from typical patterns
- **Cloud Environments**: Serverless and containerized apps have dynamic relationships
- **Microservices**: Modern architectures may not follow traditional ecosystem boundaries
- **Custom Integrations**: Undocumented APIs and integrations create hidden relationships
- **Probability Estimates**: Confidence levels are heuristic, not empirically validated
- **Version Variations**: Different software versions may have different dependencies
- **Configuration Differences**: Same software stack may be configured differently per environment
- **Third-Party Services**: SaaS and external services complicate ecosystem boundaries

## Source Excerpts

### [S1] Software Ecosystem Relationships Definition
```python
# From vul_correlators.py lines 18-23
self.software_relationships = {
    "windows": ["iis", "office", "exchange", "sharepoint"],
    "linux": ["apache", "nginx", "mysql", "postgresql"],
    "web": ["php", "nodejs", "python", "java"],
    "database": ["mysql", "postgresql", "oracle", "mssql"]
}
```

## References
- **MITRE ATT&CK T1210 - Exploitation of Remote Services** - https://attack.mitre.org/techniques/T1210/
- **MITRE ATT&CK T1021 - Remote Services** - https://attack.mitre.org/techniques/T1021/
- **MITRE ATT&CK T1078 - Valid Accounts** - https://attack.mitre.org/techniques/T1078/
- **NIST SP 800-53 Rev. 5 - SC-7 Boundary Protection** - https://csrc.nist.gov/publications/detail/sp/800-53/rev-5/final
- **CIS Controls v8 - Control 12: Network Infrastructure Management** - https://www.cisecurity.org/controls/v8
- **Zero Trust Architecture (NIST SP 800-207)** - https://csrc.nist.gov/publications/detail/sp/800-207/final
