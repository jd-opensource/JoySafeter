'use client';

/**
 * WhiteboxScan page - main page for whitebox scanning feature
 * Migrated from frontend_dynamic/web to Next.js App Router
 */

import { useRouter } from 'next/navigation';
import React, { useState } from 'react';

import { UploadBox, ScanReport } from '@/components/dynamic/whitebox';
import { scanApi, ScanJobStatus, ScanReport as ScanReportType } from '@/lib/api/dynamic/scanApi';
import '@/styles/dynamic/whitebox/WhiteboxScan.css';
import '@/styles/dynamic/whitebox/UploadBox.css';
import '@/styles/dynamic/whitebox/ScanReport.css';
import '@/styles/dynamic/whitebox/FindingList.css';

type ScanState = 'idle' | 'uploading' | 'scanning' | 'completed' | 'error';

export default function WhiteboxScanPage() {
  const router = useRouter();
  const [state, setState] = useState<ScanState>('idle');
  const [jobId, setJobId] = useState<string | null>(null);
  const [progress, setProgress] = useState(0);
  const [report, setReport] = useState<ScanReportType | null>(null);
  const [error, setError] = useState<string | null>(null);

  const handleUpload = async (file: File) => {
    try {
      setState('uploading');
      setError(null);
      setProgress(0);

      // Start scan
      const response = await scanApi.uploadZip(file);
      setJobId(response.job_id);
      setState('scanning');

      // Poll for status
      await scanApi.pollScanStatus(
        response.job_id,
        (status: ScanJobStatus) => {
          setProgress(status.progress);

          if (status.status === 'COMPLETED' && status.result) {
            setReport(status.result);
            setState('completed');
          } else if (status.status === 'FAILED') {
            setError(status.error || 'Scan failed');
            setState('error');
          }
        }
      );
    } catch (err) {
      console.error('Scan error:', err);
      setError(err instanceof Error ? err.message : 'Unknown error');
      setState('error');
    }
  };

  const handleReset = () => {
    setState('idle');
    setJobId(null);
    setProgress(0);
    setReport(null);
    setError(null);
  };

  return (
    <div className="whitebox-scan">
      <div className="scan-header">
        <div className="flex items-center gap-4 mb-4">
          <button
            onClick={() => router.push('/dynamic-chat')}
            className="flex items-center gap-2 px-4 py-2 rounded-lg bg-gray-200 hover:bg-gray-300 dark:bg-gray-700 dark:hover:bg-gray-600 text-gray-700 dark:text-gray-200 text-sm font-medium transition-all duration-200"
          >
            <svg
              className="w-5 h-5"
              fill="none"
              stroke="currentColor"
              viewBox="0 0 24 24"
            >
              <path
                strokeLinecap="round"
                strokeLinejoin="round"
                strokeWidth={2}
                d="M10 19l-7-7m0 0l7-7m-7 7h18"
              />
            </svg>
            <span>Back to Chat</span>
          </button>
        </div>
        <h1>Whitebox Vulnerability Scanner</h1>
        <p className="scan-description">
          Upload your source code as a ZIP file to scan for potential security vulnerabilities.
          Our AI-powered scanner uses pattern matching and taint analysis to identify issues.
        </p>
      </div>

      <div className="scan-content">
        {state === 'idle' && (
          <UploadBox onUpload={handleUpload} isUploading={false} />
        )}

        {(state === 'uploading' || state === 'scanning') && (
          <div className="scan-progress">
            <UploadBox onUpload={handleUpload} isUploading={true} />
            <div className="progress-details">
              <div className="progress-bar-container">
                <div
                  className="progress-bar"
                  style={{ width: `${progress}%` }}
                ></div>
              </div>
              <p className="progress-text">
                {state === 'uploading' ? 'Uploading file...' : `Scanning... ${progress}%`}
              </p>
              <p className="progress-subtext">
                This may take a few moments. Please don't close this window.
              </p>
            </div>
          </div>
        )}

        {state === 'completed' && report && (
          <ScanReport report={report} onBack={handleReset} />
        )}

        {state === 'error' && (
          <div className="scan-error">
            <div className="error-icon">⚠️</div>
            <h3>Scan Failed</h3>
            <p className="error-message">{error}</p>
            <button className="retry-button" onClick={handleReset}>
              Try Again
            </button>
          </div>
        )}
      </div>

      <div className="scan-footer">
        <h3>Supported Vulnerability Types</h3>
        <ul className="vulnerability-types">
          <li>
            <span className="vuln-type">SQL Injection</span>
            <span className="vuln-desc">Detects potential SQL injection vulnerabilities</span>
          </li>
          <li>
            <span className="vuln-type">Hardcoded Secrets</span>
            <span className="vuln-desc">Finds API keys, passwords, and tokens in code</span>
          </li>
          <li>
            <span className="vuln-type">XSS</span>
            <span className="vuln-desc">Identifies cross-site scripting vulnerabilities</span>
          </li>
        </ul>
      </div>
    </div>
  );
}
