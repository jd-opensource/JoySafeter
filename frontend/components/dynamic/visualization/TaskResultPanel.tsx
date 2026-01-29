/**
 * TaskResultPanel Component
 * Displays task execution results in Markdown format
 */

import React from 'react';

import { Task } from '@/types/dynamic/execution';
import '@/styles/dynamic/visualization/TaskResultPanel.css';

interface TaskResultPanelProps {
  task: Task | null;
}

/**
 * TaskResultPanel component - displays task results
 */
export const TaskResultPanel: React.FC<TaskResultPanelProps> = ({ task }) => {
  if (!task) {
    return (
      <div className="task-result-panel">
        <div className="result-empty">
          <p>No task selected</p>
        </div>
      </div>
    );
  }

  // If task has result_summary, display it
  if (task.result_summary) {
    return (
      <div className="task-result-panel">
        <div className="result-content">
          <div className="markdown-viewer">
            <MarkdownContent content={task.result_summary} />
          </div>
        </div>
      </div>
    );
  }

  // Generate sample markdown result based on task
  const generateSampleResult = (): string => {
    const resultMap: Record<string, string> = {
      'Network Reconnaissance': `# Network Reconnaissance Report

## Executive Summary
Comprehensive network scan completed successfully with detailed topology mapping.

## Findings

### Network Topology
- **Total Hosts Discovered**: 42
- **Active Services**: 156
- **Open Ports**: 89
- **Closed Ports**: 234

### Host Details
| Host | OS | Services | Risk Level |
|------|----|-----------|----|
| 192.168.1.1 | Linux | SSH, HTTP, HTTPS | Low |
| 192.168.1.10 | Windows | RDP, SMB | Medium |
| 192.168.1.20 | Linux | MySQL, HTTP | High |

### Network Segments
1. **DMZ**: 10 hosts, 45 services
2. **Internal**: 20 hosts, 78 services
3. **Management**: 12 hosts, 33 services

## Recommendations
- Update firewall rules for segment isolation
- Implement network segmentation
- Enable network monitoring

---
*Report Generated: ${new Date().toLocaleString()}*`,

      'Vulnerability Scanning': `# Vulnerability Scan Report

## Summary
Vulnerability assessment completed. Found 12 issues requiring attention.

## Critical Issues (3)
- **CVE-2024-1234**: Remote Code Execution in Apache
  - CVSS Score: 9.8
  - Affected: 3 servers
  - Status: Unpatched

- **CVE-2024-5678**: SQL Injection in Web App
  - CVSS Score: 8.9
  - Affected: 1 server
  - Status: Unpatched

- **CVE-2024-9012**: Privilege Escalation
  - CVSS Score: 8.5
  - Affected: 2 servers
  - Status: Unpatched

## High Issues (4)
- Weak SSL Configuration
- Missing Security Headers
- Outdated Libraries
- Unencrypted Data Transmission

## Medium Issues (5)
- Default Credentials
- Information Disclosure
- Missing Input Validation
- Weak Password Policy
- Insecure Session Management

## Remediation Plan
1. Patch critical vulnerabilities (Priority: Immediate)
2. Update SSL configuration (Priority: High)
3. Implement security headers (Priority: High)
4. Update libraries (Priority: Medium)

---
*Scan Date: ${new Date().toLocaleString()}*`,

      'Penetration Testing': `# Penetration Test Report

## Engagement Overview
- **Scope**: Full infrastructure assessment
- **Duration**: 5 days
- **Testers**: 2 security professionals
- **Status**: Completed

## Executive Summary
Successfully demonstrated multiple attack vectors. Overall security posture: **FAIR**

## Attack Vectors Demonstrated

### 1. Social Engineering
- Success Rate: 60%
- Phishing emails: 3 successful
- Phone pretexting: 2 successful

### 2. Network Exploitation
- Lateral movement: Successful
- Privilege escalation: Successful
- Data exfiltration: Successful

### 3. Web Application
- SQL Injection: Exploited
- XSS Vulnerabilities: 5 found
- CSRF: Exploitable

## Risk Assessment
| Category | Risk Level | Count |
|----------|-----------|-------|
| Critical | High | 3 |
| High | Medium | 8 |
| Medium | Low | 15 |

## Key Findings
1. Insufficient network segmentation
2. Weak access controls
3. Poor logging and monitoring
4. Outdated systems

## Recommendations
1. Implement zero-trust architecture
2. Enhance monitoring and alerting
3. Regular security training
4. Patch management program

---
*Report Generated: ${new Date().toLocaleString()}*`,

      'Security Assessment': `# Security Assessment Report

## Assessment Scope
Comprehensive security evaluation of IT infrastructure and processes.

## Assessment Results

### Infrastructure Security: 72/100
- Network Security: 68/100
- Server Security: 75/100
- Database Security: 70/100
- Application Security: 78/100

### Process Security: 65/100
- Access Control: 70/100
- Change Management: 60/100
- Incident Response: 65/100
- Disaster Recovery: 62/100

### Compliance: 58/100
- GDPR Compliance: 55/100
- ISO 27001: 60/100
- SOC 2: 58/100

## Strengths
✓ Good firewall configuration
✓ Regular backups in place
✓ Multi-factor authentication enabled
✓ Incident response team established

## Weaknesses
✗ Insufficient logging
✗ Weak password policies
✗ Limited monitoring
✗ Poor documentation

## Action Items
1. Implement comprehensive logging (Priority: High)
2. Enforce strong password policy (Priority: High)
3. Deploy SIEM solution (Priority: Medium)
4. Create security documentation (Priority: Medium)

---
*Assessment Date: ${new Date().toLocaleString()}*`,

      'System Analysis': `# System Analysis Report

## System Overview
Detailed analysis of system configuration and performance.

## Hardware Inventory
- **Servers**: 15
- **Workstations**: 120
- **Network Devices**: 8
- **Storage**: 50TB

## Software Inventory
- **Operating Systems**: Windows (60%), Linux (40%)
- **Databases**: PostgreSQL, MySQL, SQL Server
- **Applications**: 200+ installed

## Performance Metrics
- **CPU Utilization**: 45% average
- **Memory Usage**: 62% average
- **Disk Usage**: 78% average
- **Network Bandwidth**: 35% average

## Configuration Issues
1. Inconsistent patch levels
2. Non-standard configurations
3. Unauthorized software
4. Missing security controls

## Recommendations
1. Standardize configurations
2. Implement configuration management
3. Deploy asset tracking
4. Enforce software policies

---
*Analysis Date: ${new Date().toLocaleString()}*`,

      'Data Collection': `# Data Collection Report

## Collection Summary
Successfully collected security-relevant data from all systems.

## Data Categories
- **System Logs**: 2.5GB
- **Application Logs**: 1.8GB
- **Security Events**: 450MB
- **Network Traffic**: 5.2GB

## Key Metrics
- Total Events Collected: 1,250,000
- Unique Sources: 156
- Collection Duration: 24 hours
- Success Rate: 99.8%

## Data Quality
- Completeness: 98%
- Accuracy: 99%
- Timeliness: 100%

## Notable Events
- 45 failed login attempts
- 12 privilege escalation attempts
- 8 firewall blocks
- 3 antivirus detections

## Data Retention
- Raw data: 30 days
- Processed data: 90 days
- Reports: 1 year

---
*Collection Date: ${new Date().toLocaleString()}*`,

      'Risk Evaluation': `# Risk Evaluation Report

## Risk Assessment Summary
Comprehensive risk evaluation completed.

## Risk Matrix
| Risk | Probability | Impact | Score |
|------|------------|--------|-------|
| Data Breach | High | Critical | 9.0 |
| System Outage | Medium | High | 7.5 |
| Malware Infection | Medium | High | 7.0 |
| Unauthorized Access | Medium | Medium | 6.0 |

## Top Risks
1. **Data Breach Risk**: 9.0/10
   - Likelihood: High
   - Impact: Critical
   - Mitigation: Encryption, access controls

2. **System Outage Risk**: 7.5/10
   - Likelihood: Medium
   - Impact: High
   - Mitigation: Redundancy, failover

3. **Malware Risk**: 7.0/10
   - Likelihood: Medium
   - Impact: High
   - Mitigation: Antivirus, EDR

## Risk Mitigation Plan
- Implement defense in depth
- Regular security updates
- Employee training program
- Incident response procedures

---
*Evaluation Date: ${new Date().toLocaleString()}*`,

      'Threat Detection': `# Threat Detection Report

## Detection Summary
Threat detection systems monitored all infrastructure.

## Threats Detected
- **Malware**: 23 instances
- **Intrusion Attempts**: 156
- **Suspicious Activities**: 89
- **Policy Violations**: 34

## Threat Details

### Critical Threats (2)
1. Ransomware variant detected on server-05
   - Status: Quarantined
   - Action: Isolated and cleaned

2. Botnet C2 communication detected
   - Status: Blocked
   - Action: Firewall rule added

### High Threats (8)
- Privilege escalation attempts
- Lateral movement detected
- Data exfiltration attempts
- Unauthorized access attempts

## Detection Methods
- Signature-based detection
- Anomaly detection
- Behavior analysis
- Threat intelligence

## Response Actions
1. Immediate isolation of affected systems
2. Forensic analysis initiated
3. Threat intelligence shared
4. Security controls enhanced

---
*Detection Period: Last 7 days*
*Report Date: ${new Date().toLocaleString()}*`,
    };

    return resultMap[task.title] || `# ${task.title} Results

## Task Execution Summary
- **Status**: ${task.status}
- **Duration**: ${Math.round(task.duration_ms / 1000)} seconds
- **Agents Used**: ${task.agent_count}
- **Tools Executed**: ${task.tool_count}
- **Success Rate**: ${task.success_rate}%

## Results
Task execution completed successfully. Detailed results and analysis are available above.

${task.error_message ? `## Error Details\n\n\`\`\`\n${task.error_message}\n\`\`\`` : ''}

---
*Generated: ${new Date().toLocaleString()}*`;
  };

  const markdownResult = generateSampleResult();

  return (
    <div className="task-result-panel">
      <div className="result-content">
        <div className="markdown-viewer">
          <MarkdownContent content={markdownResult} />
        </div>
      </div>
    </div>
  );
};

/**
 * MarkdownContent component - renders markdown as HTML
 */
interface MarkdownContentProps {
  content: string;
}

const MarkdownContent: React.FC<MarkdownContentProps> = ({ content }) => {
  const renderMarkdown = (md: string): React.ReactNode[] => {
    const lines = md.split('\n');
    const elements: React.ReactNode[] = [];
    let inCodeBlock = false;
    let codeContent = '';
    let inTable = false;
    let tableRows: string[][] = [];

    for (let i = 0; i < lines.length; i++) {
      const line = lines[i];

      // Code blocks
      if (line.startsWith('```')) {
        if (inCodeBlock) {
          elements.push(
            <pre key={`code-${i}`} className="markdown-code">
              <code>{codeContent}</code>
            </pre>
          );
          codeContent = '';
          inCodeBlock = false;
        } else {
          inCodeBlock = true;
        }
        continue;
      }

      if (inCodeBlock) {
        codeContent += line + '\n';
        continue;
      }

      // Tables
      if (line.includes('|')) {
        if (!inTable) {
          inTable = true;
          tableRows = [];
        }
        const cells = line.split('|').filter((cell) => cell.trim());
        if (cells.length > 0) {
          tableRows.push(cells);
        }
        continue;
      } else if (inTable) {
        // End of table
        if (tableRows.length > 0) {
          elements.push(
            <table key={`table-${i}`} className="markdown-table">
              <thead>
                <tr>
                  {tableRows[0].map((cell, idx) => (
                    <th key={idx}>{cell.trim()}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {tableRows.slice(1).map((row, rowIdx) => (
                  <tr key={rowIdx}>
                    {row.map((cell, cellIdx) => (
                      <td key={cellIdx}>{cell.trim()}</td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          );
        }
        inTable = false;
        tableRows = [];
      }

      // Headings
      if (line.startsWith('# ')) {
        elements.push(
          <h1 key={`h1-${i}`} className="markdown-h1">
            {line.substring(2)}
          </h1>
        );
        continue;
      }
      if (line.startsWith('## ')) {
        elements.push(
          <h2 key={`h2-${i}`} className="markdown-h2">
            {line.substring(3)}
          </h2>
        );
        continue;
      }
      if (line.startsWith('### ')) {
        elements.push(
          <h3 key={`h3-${i}`} className="markdown-h3">
            {line.substring(4)}
          </h3>
        );
        continue;
      }

      // Horizontal rule
      if (line.startsWith('---') || line.startsWith('***')) {
        elements.push(<hr key={`hr-${i}`} className="markdown-hr" />);
        continue;
      }

      // Lists
      if (line.startsWith('- ')) {
        elements.push(
          <li key={`li-${i}`} className="markdown-li">
            {line.substring(2)}
          </li>
        );
        continue;
      }

      // Checkmarks and crosses
      if (line.includes('✓') || line.includes('✗')) {
        elements.push(
          <div key={`check-${i}`} className="markdown-check">
            {line}
          </div>
        );
        continue;
      }

      // Bold and italic
      const processedLine = line
        .replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>')
        .replace(/\*(.*?)\*/g, '<em>$1</em>')
        .replace(/`(.*?)`/g, '<code>$1</code>');

      // Regular paragraph
      if (line.trim()) {
        elements.push(
          <p key={`p-${i}`} className="markdown-p">
            {processedLine}
          </p>
        );
      }
    }

    return elements;
  };

  return <div className="markdown-content">{renderMarkdown(content)}</div>;
};

TaskResultPanel.displayName = 'TaskResultPanel';
