/**
 * API service for whitebox scanning
 */

import axios from 'axios';

import { getApiBaseUrl } from './apiConfig';

const API_BASE_URL = getApiBaseUrl();

export interface Finding {
  id: string;
  rule_id: string;
  type: string;
  severity: 'HIGH' | 'MEDIUM' | 'LOW' | 'INFO';
  file_path: string;
  line_number: number;
  code_snippet: string;
  agent_verification: string;
  agent_comment?: string;
}

export interface ScanReport {
  summary: {
    total: number;
    high: number;
    medium: number;
    low: number;
    info: number;
  };
  findings: Finding[];
  scanned_files: number;
  scan_duration_ms: number;
}

export interface ScanJobResponse {
  job_id: string;
  status: 'QUEUED' | 'PROCESSING';
  message: string;
}

export interface ScanJobStatus {
  job_id: string;
  status: 'QUEUED' | 'PROCESSING' | 'COMPLETED' | 'FAILED';
  progress: number;
  error?: string;
  result?: ScanReport;
}

export class ScanApiService {
  /**
   * Upload a ZIP file and start a scan
   */
  async uploadZip(file: File): Promise<ScanJobResponse> {
    const formData = new FormData();
    formData.append('file', file);

    const response = await axios.post<ScanJobResponse>(
      `${API_BASE_URL}/api/scan/upload`,
      formData,
      {
        headers: {
          'Content-Type': 'multipart/form-data',
        },
      }
    );

    return response.data;
  }

  /**
   * Get the status of a scan job
   */
  async getScanStatus(jobId: string): Promise<ScanJobStatus> {
    const response = await axios.get<ScanJobStatus>(
      `${API_BASE_URL}/api/scan/status/${jobId}`
    );

    return response.data;
  }

  /**
   * Poll scan status until completion
   */
  async pollScanStatus(
    jobId: string,
    onProgress?: (status: ScanJobStatus) => void,
    intervalMs: number = 2000
  ): Promise<ScanJobStatus> {
    return new Promise((resolve, reject) => {
      const poll = async () => {
        try {
          const status = await this.getScanStatus(jobId);

          if (onProgress) {
            onProgress(status);
          }

          if (status.status === 'COMPLETED') {
            resolve(status);
          } else if (status.status === 'FAILED') {
            reject(new Error(status.error || 'Scan failed'));
          } else {
            setTimeout(poll, intervalMs);
          }
        } catch (error) {
          reject(error);
        }
      };

      poll();
    });
  }
}

export const scanApi = new ScanApiService();
