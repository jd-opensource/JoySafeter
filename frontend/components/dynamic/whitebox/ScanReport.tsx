/**
 * ScanReport component - displays scan summary and findings
 */

import React from 'react';

import { ScanReport as ScanReportType, Finding } from '@/lib/api/dynamic/scanApi';

import { FindingList } from './FindingList';
import '@/styles/dynamic/whitebox/ScanReport.css';

interface ScanReportProps {
  report: ScanReportType;
  onBack: () => void;
}

export const ScanReport: React.FC<ScanReportProps> = ({ report, onBack }) => {
  const { summary, findings, scanned_files, scan_duration_ms } = report;

  const getSeverityColor = (severity: string) => {
    switch (severity) {
      case 'HIGH':
        return '#dc3545';
      case 'MEDIUM':
        return '#ffc107';
      case 'LOW':
        return '#28a745';
      case 'INFO':
        return '#17a2b8';
      default:
        return '#6c757d';
    }
  };

  return (
    <div className="scan-report">
      <div className="report-header">
        <button className="back-button" onClick={onBack}>
          ← Back
        </button>
        <h2>Scan Report</h2>
      </div>

      <div className="report-summary">
        <div className="summary-card">
          <div className="summary-stat">
            <span className="stat-value">{summary.total}</span>
            <span className="stat-label">Total Findings</span>
          </div>
          <div className="summary-stat high">
            <span className="stat-value" style={{ color: getSeverityColor('HIGH') }}>
              {summary.high}
            </span>
            <span className="stat-label">High</span>
          </div>
          <div className="summary-stat medium">
            <span className="stat-value" style={{ color: getSeverityColor('MEDIUM') }}>
              {summary.medium}
            </span>
            <span className="stat-label">Medium</span>
          </div>
          <div className="summary-stat low">
            <span className="stat-value" style={{ color: getSeverityColor('LOW') }}>
              {summary.low}
            </span>
            <span className="stat-label">Low</span>
          </div>
          <div className="summary-stat info">
            <span className="stat-value" style={{ color: getSeverityColor('INFO') }}>
              {summary.info}
            </span>
            <span className="stat-label">Info</span>
          </div>
        </div>

        <div className="scan-metadata">
          <div className="metadata-item">
            <span className="metadata-label">Files Scanned:</span>
            <span className="metadata-value">{scanned_files}</span>
          </div>
          <div className="metadata-item">
            <span className="metadata-label">Scan Duration:</span>
            <span className="metadata-value">{(scan_duration_ms / 1000).toFixed(2)}s</span>
          </div>
        </div>
      </div>

      <div className="findings-section">
        <h3>Vulnerability Findings</h3>
        <FindingList findings={findings} />
      </div>
    </div>
  );
};

