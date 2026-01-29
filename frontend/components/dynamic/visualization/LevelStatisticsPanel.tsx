/**
 * LevelStatisticsPanel Component
 * Displays statistics for each execution level
 */

import React, { useMemo } from 'react';

import { formatDuration } from '@/lib/utils/dynamic/formatting';
import { calculateLevelStatistics } from '@/lib/utils/dynamic/levelUtils';
import { ExecutionTree } from '@/types/dynamic/execution';
import '@/styles/dynamic/visualization/LevelStatisticsPanel.css';

interface LevelStatisticsPanelProps {
  execution: ExecutionTree;
}

/**
 * LevelStatisticsPanel component - displays statistics for each execution level
 * 
 * Props:
 * - execution: ExecutionTree to calculate statistics from
 * 
 * Features:
 * - Statistics table with Level, Agents, Tools, Avg Duration, Success Rate
 * - Success rate progress bars with color coding (green/orange/red)
 * - Summary statistics at bottom
 * - Responsive grid layout
 * 
 * Performance: Memoized to prevent unnecessary re-renders
 */
export const LevelStatisticsPanel: React.FC<LevelStatisticsPanelProps> = React.memo(({ execution }) => {
  const statistics = useMemo(() => calculateLevelStatistics(execution), [execution]);

  if (statistics.length === 0) {
    return (
      <div className="level-stats-panel">
        <div className="level-stats-empty">
          <div className="empty-icon">📊</div>
          <div className="empty-text">No level statistics available</div>
        </div>
      </div>
    );
  }

  return (
    <div className="level-stats-panel">
      <div className="level-stats-header">
        <h3>Level Statistics</h3>
        <span className="level-count">{statistics.length} levels</span>
      </div>

      <div className="level-stats-table">
        <div className="table-header">
          <div className="col-level">Level</div>
          <div className="col-agents">Agents</div>
          <div className="col-tools">Tools</div>
          <div className="col-duration">Avg Duration</div>
          <div className="col-success">Success Rate</div>
        </div>

        <div className="table-body">
          {statistics.map((stat) => (
            <div key={stat.level} className="table-row">
              <div className="col-level">
                <span className="level-badge">Level {stat.level}</span>
              </div>
              <div className="col-agents">
                <span className="stat-value">{stat.agent_count}</span>
              </div>
              <div className="col-tools">
                <span className="stat-value">{stat.tool_count}</span>
              </div>
              <div className="col-duration">
                <span className="stat-value">{formatDuration(stat.avg_duration_ms)}</span>
              </div>
              <div className="col-success">
                <div className="success-bar-container">
                  <div
                    className="success-bar"
                    style={{
                      width: `${stat.success_rate}%`,
                      backgroundColor: stat.success_rate >= 80 ? '#10b981' : stat.success_rate >= 50 ? '#f59e0b' : '#ef4444',
                    }}
                  />
                  <span className="success-text">{Math.round(stat.success_rate)}%</span>
                </div>
              </div>
            </div>
          ))}
        </div>
      </div>

      <div className="level-stats-summary">
        <div className="summary-item">
          <span className="summary-label">Total Levels:</span>
          <span className="summary-value">{statistics.length}</span>
        </div>
        <div className="summary-item">
          <span className="summary-label">Total Agents:</span>
          <span className="summary-value">{statistics.reduce((sum, s) => sum + s.agent_count, 0)}</span>
        </div>
        <div className="summary-item">
          <span className="summary-label">Total Tools:</span>
          <span className="summary-value">{statistics.reduce((sum, s) => sum + s.tool_count, 0)}</span>
        </div>
        <div className="summary-item">
          <span className="summary-label">Overall Success:</span>
          <span className="summary-value">
            {Math.round(statistics.reduce((sum, s) => sum + s.success_rate, 0) / statistics.length)}%
          </span>
        </div>
      </div>
    </div>
  );
});

LevelStatisticsPanel.displayName = 'LevelStatisticsPanel';
