/**
 * FindingList component - displays a list of vulnerability findings
 */

import React, { useState } from 'react';

import { Finding } from '@/lib/api/dynamic/scanApi';
import '@/styles/dynamic/whitebox/FindingList.css';

interface FindingListProps {
  findings: Finding[];
}

interface ExpandedFinding {
  [key: string]: boolean;
}

export const FindingList: React.FC<FindingListProps> = ({ findings }) => {
  const [expanded, setExpanded] = useState<ExpandedFinding>({});

  const toggleExpanded = (id: string) => {
    setExpanded(prev => ({
      ...prev,
      [id]: !prev[id]
    }));
  };

  const getSeverityBadgeClass = (severity: string) => {
    return `severity-badge severity-${severity.toLowerCase()}`;
  };

  const getAgentVerificationIcon = (verification: string) => {
    switch (verification) {
      case 'VERIFIED':
        return '✓';
      case 'FALSE_POSITIVE':
        return '✗';
      case 'UNCERTAIN':
        return '?';
      case 'NOT_REQUIRED':
        return '−';
      default:
        return '...';
    }
  };

  if (findings.length === 0) {
    return (
      <div className="no-findings">
        <p>No vulnerabilities found! 🎉</p>
      </div>
    );
  }

  return (
    <div className="finding-list">
      {findings.map((finding) => (
        <div key={finding.id} className="finding-item">
          <div
            className="finding-header"
            onClick={() => toggleExpanded(finding.id)}
          >
            <div className="finding-info">
              <span className={getSeverityBadgeClass(finding.severity)}>
                {finding.severity}
              </span>
              <span className="finding-type">{finding.type}</span>
              <span className="finding-path">
                {finding.file_path}:{finding.line_number}
              </span>
            </div>
            <div className="finding-actions">
              <span className="agent-verification">
                <span className="verification-icon">
                  {getAgentVerificationIcon(finding.agent_verification)}
                </span>
                <span className="verification-text">
                  {finding.agent_verification}
                </span>
              </span>
              <span className="expand-icon">
                {expanded[finding.id] ? '▲' : '▼'}
              </span>
            </div>
          </div>

          {expanded[finding.id] && (
            <div className="finding-details">
              <div className="code-snippet">
                <div className="snippet-header">
                  <strong>Code Snippet:</strong>
                </div>
                <pre className="snippet-content">
                  <code>{finding.code_snippet}</code>
                </pre>
              </div>

              {finding.agent_comment && (
                <div className="agent-comment">
                  <div className="comment-header">
                    <strong>Agent Analysis:</strong>
                  </div>
                  <p className="comment-content">{finding.agent_comment}</p>
                </div>
              )}

              <div className="finding-meta">
                <div className="meta-item">
                  <span className="meta-label">Rule ID:</span>
                  <span className="meta-value">{finding.rule_id}</span>
                </div>
                <div className="meta-item">
                  <span className="meta-label">Finding ID:</span>
                  <span className="meta-value">{finding.id}</span>
                </div>
              </div>
            </div>
          )}
        </div>
      ))}
    </div>
  );
};
