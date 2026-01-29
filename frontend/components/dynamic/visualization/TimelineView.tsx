/**
 * TimelineView Component
 * Displays agent execution as a horizontal timeline with concurrent grouping
 */

import React, { useMemo } from 'react';

import { formatDuration, formatTimestamp } from '@/lib/utils/dynamic/formatting';
import { useExecutionStore } from '@/stores/dynamic/executionStore';
import { ExecutionTimeline } from '@/types/dynamic/execution';
import '@/styles/dynamic/visualization/TimelineView.css';

interface TimelineViewProps {
  timeline: ExecutionTimeline;
}

/**
 * TimelineView component - renders agents on a horizontal timeline
 */
export const TimelineView: React.FC<TimelineViewProps> = ({ timeline }) => {
  const selectedAgentId = useExecutionStore((state) => state.selectedAgentId);
  const selectAgent = useExecutionStore((state) => state.selectAgent);

  const maxRow = useMemo(() => {
    return Math.max(...timeline.agents.map((ta) => ta.row), 0);
  }, [timeline.agents]);


  const getStatusColor = (status: string): string => {
    switch (status) {
      case 'completed':
        return '#10b981';
      case 'running':
        return '#3b82f6';
      case 'failed':
        return '#ef4444';
      case 'pending':
        return '#9ca3af';
      default:
        return '#6b7280';
    }
  };

  return (
    <div className="timeline-view">
      <div className="timeline-header">
        <div className="timeline-title">Execution Timeline</div>
        <div className="timeline-stats">
          <span>Total Duration: {formatDuration(timeline.total_duration_ms)}</span>
          <span>Agents: {timeline.agents.length}</span>
        </div>
      </div>

      <div className="timeline-container">
        <div className="timeline-ruler">
          <div className="ruler-labels">
            <div className="ruler-label">0ms</div>
            <div className="ruler-label">{formatDuration(timeline.total_duration_ms / 4)}</div>
            <div className="ruler-label">{formatDuration(timeline.total_duration_ms / 2)}</div>
            <div className="ruler-label">{formatDuration((timeline.total_duration_ms * 3) / 4)}</div>
            <div className="ruler-label">{formatDuration(timeline.total_duration_ms)}</div>
          </div>
          <div className="ruler-line" />
        </div>

        <div className="timeline-tracks">
          {Array.from({ length: maxRow + 1 }).map((_, rowIndex) => {
            const agentsInRow = timeline.agents.filter((ta) => ta.row === rowIndex);

            return (
              <div key={rowIndex} className="timeline-track">
                <div className="track-label">Row {rowIndex + 1}</div>
                <div className="track-content">
                  {agentsInRow.map((timelineAgent) => {
                    const isSelected = selectedAgentId === timelineAgent.agent.id;
                    const left = (timelineAgent.offset_ms / timeline.total_duration_ms) * 100;
                    const width = (timelineAgent.width_ms / timeline.total_duration_ms) * 100;
                    const statusColor = getStatusColor(timelineAgent.agent.status);

                    return (
                      <div
                        key={timelineAgent.agent.id}
                        className={`timeline-bar ${isSelected ? 'selected' : ''}`}
                        style={{
                          left: `${left}%`,
                          width: `${width}%`,
                          backgroundColor: statusColor,
                        }}
                        onClick={() => selectAgent(timelineAgent.agent.id)}
                        title={timelineAgent.agent.name}
                      >
                        <div className="bar-label">{timelineAgent.agent.name}</div>
                        <div className="bar-tooltip">
                          <div className="tooltip-item">
                            <strong>{timelineAgent.agent.name}</strong>
                          </div>
                          <div className="tooltip-item">
                            Duration: {formatDuration(timelineAgent.agent.duration_ms)}
                          </div>
                          <div className="tooltip-item">
                            Start: {formatTimestamp(timelineAgent.agent.start_time)}
                          </div>
                          <div className="tooltip-item">
                            End: {formatTimestamp(timelineAgent.agent.end_time)}
                          </div>
                          <div className="tooltip-item">Status: {timelineAgent.agent.status}</div>
                        </div>
                      </div>
                    );
                  })}
                </div>
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
};

TimelineView.displayName = 'TimelineView';
