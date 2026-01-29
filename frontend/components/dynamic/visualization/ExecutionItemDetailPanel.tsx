/**
 * ExecutionItemDetailPanel Component
 * Unified detail panel for displaying Agent or Tool information
 */

import React from 'react';
import ReactMarkdown from 'react-markdown';
import { Prism as SyntaxHighlighter } from 'react-syntax-highlighter';
import { vscDarkPlus } from 'react-syntax-highlighter/dist/esm/styles/prism';

import { formatDuration, formatTimestamp } from '@/lib/utils/dynamic/formatting';
import { Agent, ToolInvocation } from '@/types/dynamic/execution';
import '@/styles/dynamic/visualization/ExecutionItemDetailPanel.css';

interface ExecutionItemDetailPanelProps {
  item: Agent | ToolInvocation | null;
  itemType: 'agent' | 'tool' | null;
}

/**
 * ExecutionItemDetailPanel component - shows detailed information for Agent or Tool
 */
export const ExecutionItemDetailPanel: React.FC<ExecutionItemDetailPanelProps> = ({ item, itemType }) => {
  // State for tools list expansion
  const [toolsExpanded, setToolsExpanded] = React.useState(false);

  if (!item || !itemType) {
    return (
      <div className="execution-item-detail-panel empty">
        <div className="empty-state">
          <div className="empty-icon">👆</div>
          <p>Select an agent or tool to view details</p>
        </div>
      </div>
    );
  }

  const isAgent = itemType === 'agent';
  const agent = isAgent ? (item as Agent) : null;
  const tool = !isAgent ? (item as ToolInvocation) : null;

  return (
    <div className="execution-item-detail-panel">
      {/* Header */}
      <div className="detail-panel-header">
        <div className="item-title">
          <span className="item-icon">{isAgent ? '🤖' : '🔧'}</span>
          <h3>{isAgent ? agent!.name : tool!.tool_name}</h3>
          <span className={`status-badge ${item.status}`}>{item.status}</span>
        </div>
        <div className="item-type-badge">
          {isAgent ? 'Agent' : 'Tool'}
        </div>
      </div>

      {/* ID Information */}
      <div className="detail-section id-section">
        <h4 className="section-title">🔑 Identifiers</h4>
        <div className="id-grid">
          {isAgent && (
            <>
              <div className="id-item">
                <span className="id-label">Agent ID:</span>
                <code className="id-value">{agent!.id}</code>
              </div>
              {agent!.task_id && (
                <div className="id-item">
                  <span className="id-label">Task ID:</span>
                  <code className="id-value">{agent!.task_id}</code>
                </div>
              )}
            </>
          )}
          {tool && (
            <>
              <div className="id-item">
                <span className="id-label">Step ID:</span>
                <code className="id-value">{tool.id}</code>
              </div>
              {tool.task_id && (
                <div className="id-item">
                  <span className="id-label">Task ID:</span>
                  <code className="id-value">{tool.task_id}</code>
                </div>
              )}
            </>
          )}
        </div>
      </div>

      {/* Timing Information */}
      <div className="detail-section">
        <h4 className="section-title">⏱️ Execution Time</h4>
        <div className="timing-grid">
          <div className="timing-item">
            <span className="timing-label">⏰ Start:</span>
            <span className="timing-value">{formatTimestamp(item.start_time)}</span>
          </div>
          <div className="timing-item">
            <span className="timing-label">⏱️ End:</span>
            <span className="timing-value">{formatTimestamp(item.end_time)}</span>
          </div>
          <div className="timing-item">
            <span className="timing-label">⏳ Duration:</span>
            <span className="timing-value">{formatDuration(item.duration_ms)}</span>
          </div>
        </div>
      </div>

      {/* Agent-specific: Context Information */}
      {isAgent && agent!.context && (
        <div className="detail-section">
          <h4 className="section-title">🎯 Context Information</h4>
          <div className="section-content">
            <p className="description-text">
              {typeof agent!.context === 'string' 
                ? agent!.context 
                : JSON.stringify(agent!.context, null, 2)}
            </p>
          </div>
        </div>
      )}

      {/* Agent-specific: Available Tools */}
      {isAgent && agent!.available_tools && agent!.available_tools.length > 0 && (
        <div className="detail-section">
          <h4 className="section-title">🔧 Available Tools ({agent!.available_tools.length})</h4>
          <div className="available-tools-list">
            {agent!.available_tools.map((toolName, idx) => (
              <span key={idx} className="tool-tag">{toolName}</span>
            ))}
          </div>
        </div>
      )}

      {/* Agent-specific: Tools List (from metadata) */}
      {isAgent && agent!.metadata?.tools && Array.isArray(agent!.metadata.tools) && agent!.metadata.tools.length > 0 && (
        <div className="detail-section">
          <h4 className="section-title">
            🛠️ Tools ({agent!.metadata.tools_count || agent!.metadata.tools.length})
          </h4>

          {!toolsExpanded ? (
            // Collapsed: Show first 6 tools
            <div style={{
              display: 'grid',
              gridTemplateColumns: 'repeat(auto-fill, minmax(280px, 1fr))',
              gap: '12px'
            }}>
              {agent!.metadata.tools.slice(0, 6).map((tool: any, idx: number) => (
                <div key={idx} style={{
                  padding: '12px',
                  backgroundColor: '#f8fafc',
                  borderRadius: '8px',
                  border: '1px solid #e2e8f0',
                  transition: 'all 0.2s ease'
                }}>
                  <div style={{
                    display: 'flex',
                    alignItems: 'center',
                    gap: '8px',
                    marginBottom: '6px'
                  }}>
                    <span style={{ fontSize: '16px' }}>🔧</span>
                    <span style={{
                      fontSize: '13px',
                      fontWeight: 600,
                      color: '#1e293b',
                      fontFamily: 'Monaco, Menlo, monospace',
                      wordBreak: 'break-word'
                    }}>
                      {tool.name}
                    </span>
                  </div>
                  {tool.description && (
                    <div style={{
                      fontSize: '12px',
                      color: '#64748b',
                      lineHeight: '1.5',
                      fontStyle: 'italic'
                    }}>
                      {tool.description.length > 100
                        ? `${tool.description.substring(0, 100)}...`
                        : tool.description}
                    </div>
                  )}
                </div>
              ))}
            </div>
          ) : (
            // Expanded: Show all tools
            <div style={{
              display: 'grid',
              gridTemplateColumns: 'repeat(auto-fill, minmax(280px, 1fr))',
              gap: '12px'
            }}>
              {agent!.metadata.tools.map((tool: any, idx: number) => (
                <div key={idx} style={{
                  padding: '12px',
                  backgroundColor: '#f8fafc',
                  borderRadius: '8px',
                  border: '1px solid #e2e8f0',
                  transition: 'all 0.2s ease'
                }}>
                  <div style={{
                    display: 'flex',
                    alignItems: 'center',
                    gap: '8px',
                    marginBottom: '6px'
                  }}>
                    <span style={{ fontSize: '16px' }}>🔧</span>
                    <span style={{
                      fontSize: '13px',
                      fontWeight: 600,
                      color: '#1e293b',
                      fontFamily: 'Monaco, Menlo, monospace',
                      wordBreak: 'break-word'
                    }}>
                      {tool.name}
                    </span>
                  </div>
                  {tool.description && (
                    <div style={{
                      fontSize: '12px',
                      color: '#64748b',
                      lineHeight: '1.5',
                      fontStyle: 'italic'
                    }}>
                      {tool.description.length > 100
                        ? `${tool.description.substring(0, 100)}...`
                        : tool.description}
                    </div>
                  )}
                </div>
              ))}
            </div>
          )}

          {/* Expand/Collapse Button */}
          <div style={{
            marginTop: '12px',
            display: 'flex',
            justifyContent: 'center'
          }}>
            <button
              onClick={() => setToolsExpanded(!toolsExpanded)}
              style={{
                padding: '8px 16px',
                backgroundColor: '#f1f5f9',
                border: '1px solid #e2e8f0',
                borderRadius: '6px',
                fontSize: '12px',
                color: '#475569',
                cursor: 'pointer',
                transition: 'all 0.2s ease',
                display: 'flex',
                alignItems: 'center',
                gap: '6px'
              }}
              onMouseEnter={(e) => {
                e.currentTarget.style.backgroundColor = '#e2e8f0';
                e.currentTarget.style.borderColor = '#cbd5e1';
              }}
              onMouseLeave={(e) => {
                e.currentTarget.style.backgroundColor = '#f1f5f9';
                e.currentTarget.style.borderColor = '#e2e8f0';
              }}
            >
              <span style={{
                transition: 'transform 0.2s ease',
                transform: toolsExpanded ? 'rotate(180deg)' : 'rotate(0deg)'
              }}>
                ▼
              </span>
              <span>
                {toolsExpanded
                  ? 'Collapse'
                  : agent!.metadata.tools.length > 6
                    ? `Show All (${agent!.metadata.tools.length})`
                    : 'Expand'}
              </span>
            </button>
          </div>
        </div>
      )}

      {/* Description */}
      <div className="detail-section">
        <h4 className="section-title">📝 {isAgent ? 'Task Description' : 'Tool Description'}</h4>
        <div className="section-content">
          <p className="description-text">
            {isAgent ? agent!.task_description : tool!.tool_description}
          </p>
        </div>
      </div>

      {/* Agent-specific: Final Output */}
      {isAgent && agent!.output && Object.keys(agent!.output).length > 0 && (
        <div className="detail-section">
          <h4 className="section-title">
            {agent!.status === 'completed' ? '✅ Final Output' :
             agent!.status === 'failed' ? '❌ Output (Failed)' :
             '⏳ Current Output'}
          </h4>
          {typeof agent!.output === 'string' || (agent!.output.result && typeof agent!.output.result === 'string') ? (
            // Render as markdown if output is a string
            <div className="markdown-display" style={{
              padding: '16px',
              backgroundColor: '#ffffff',
              borderRadius: '8px',
              border: '1px solid #e5e7eb'
            }}>
              <ReactMarkdown
                components={{
                  h1: ({ children }) => (
                    <h1 style={{
                      fontSize: '20px',
                      fontWeight: 700,
                      color: '#1f2937',
                      marginTop: '0',
                      marginBottom: '16px',
                      paddingBottom: '8px',
                      borderBottom: '2px solid #e5e7eb'
                    }}>{children}</h1>
                  ),
                  h2: ({ children }) => (
                    <h2 style={{
                      fontSize: '18px',
                      fontWeight: 600,
                      color: '#374151',
                      marginTop: '24px',
                      marginBottom: '12px'
                    }}>{children}</h2>
                  ),
                  h3: ({ children }) => (
                    <h3 style={{
                      fontSize: '16px',
                      fontWeight: 600,
                      color: '#4b5563',
                      marginTop: '20px',
                      marginBottom: '10px'
                    }}>{children}</h3>
                  ),
                  p: ({ children, node }: any) => {
                    // Check if this paragraph contains a code block by inspecting the AST node
                    // When markdown has a code block (```), ReactMarkdown wraps it in a paragraph
                    // We need to use div instead to avoid <p><pre> nesting which is invalid HTML
                    const hasCodeBlock = node?.children?.some((child: any) => {
                      return child?.type === 'element' && child?.tagName === 'code' &&
                             !child?.properties?.className?.includes('inline');
                    });

                    // If contains code block, render as div instead of p
                    if (hasCodeBlock) {
                      return (
                        <div style={{
                          fontSize: '14px',
                          lineHeight: '1.7',
                          color: '#374151',
                          marginBottom: '12px'
                        }}>{children}</div>
                      );
                    }

                    return (
                      <p style={{
                        fontSize: '14px',
                        lineHeight: '1.7',
                        color: '#374151',
                        marginBottom: '12px'
                      }}>{children}</p>
                    );
                  },
                  ul: ({ children }) => (
                    <ul style={{
                      paddingLeft: '20px',
                      marginBottom: '12px',
                      color: '#374151'
                    }}>{children}</ul>
                  ),
                  ol: ({ children }) => (
                    <ol style={{
                      paddingLeft: '20px',
                      marginBottom: '12px',
                      color: '#374151'
                    }}>{children}</ol>
                  ),
                  li: ({ children }) => (
                    <li style={{
                      marginBottom: '6px',
                      lineHeight: '1.6'
                    }}>{children}</li>
                  ),
                  strong: ({ children }) => (
                    <strong style={{
                      fontWeight: 600,
                      color: '#1f2937'
                    }}>{children}</strong>
                  ),
                  code: ({ inline, children }: any) => inline ? (
                    <code style={{
                      backgroundColor: '#f3f4f6',
                      color: '#dc2626',
                      padding: '2px 6px',
                      borderRadius: '4px',
                      fontSize: '13px',
                      fontFamily: 'Monaco, Menlo, monospace',
                      fontWeight: 500
                    }}>{children}</code>
                  ) : (
                    <SyntaxHighlighter
                      language="python"
                      style={vscDarkPlus}
                      customStyle={{
                        borderRadius: '6px',
                        fontSize: '12px',
                        margin: '12px 0'
                      }}
                    >
                      {String(children).replace(/\n$/, '')}
                    </SyntaxHighlighter>
                  ),
                  a: ({ href, children }) => (
                    <a
                      href={href}
                      target="_blank"
                      rel="noopener noreferrer"
                      style={{
                        color: '#2563eb',
                        textDecoration: 'underline'
                      }}
                    >{children}</a>
                  ),
                  blockquote: ({ children }) => (
                    <blockquote style={{
                      borderLeft: '4px solid #3b82f6',
                      paddingLeft: '16px',
                      margin: '12px 0',
                      color: '#6b7280',
                      fontStyle: 'italic'
                    }}>{children}</blockquote>
                  ),
                }}
              >
                {agent!.output.result || agent!.output}
              </ReactMarkdown>
            </div>
          ) : (
            // Non-string output: display as JSON
            <div className="json-display">
              <pre>{JSON.stringify(agent!.output, null, 2)}</pre>
            </div>
          )}
        </div>
      )}

      {/* Input Parameters */}
      {tool && tool.parameters && Object.keys(tool.parameters).length > 0 && (
        <div className="detail-section">
          <h4 className="section-title">📥 Input Parameters</h4>
          {tool.parameters.messages && Array.isArray(tool.parameters.messages) && tool.parameters.messages.length > 0 ? (
            // LLM type: display messages in markdown format, showing only last 2
            <div className="llm-messages-display">
              {(() => {
                const messages = tool.parameters.messages[0] || tool.parameters.messages;
                const lastTwoMessages = messages.slice(-2);
                return lastTwoMessages.map((msg: any, idx: number) => {
                  const role = msg.type || msg.role;
                  const content = msg.content;
                  const toolCalls = msg.tool_calls;

                  // Get role icon and display name
                  const roleConfig: Record<string, { icon: string; name: string; color: string }> = {
                    system: { icon: '⚙️', name: 'System', color: '#6b7280' },
                    human: { icon: '👤', name: 'User', color: '#3b82f6' },
                    assistant: { icon: '🤖', name: 'Assistant', color: '#10b981' },
                    ai: { icon: '🤖', name: 'AI', color: '#10b981' },
                    tool: { icon: '🔧', name: 'Tool', color: '#f59e0b' },
                  };

                  const config = roleConfig[role] || { icon: '💬', name: role, color: '#8b5cf6' };

                  return (
                    <div key={idx} className="message-item" style={{ marginBottom: '12px' }}>
                      {/* Role header */}
                      <div className="message-header" style={{ display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '8px' }}>
                        <span className="role-icon" style={{ fontSize: '16px' }}>{config.icon}</span>
                        <span className="role-name" style={{ fontWeight: 600, color: config.color, fontSize: '13px' }}>
                          {config.name}
                        </span>
                      </div>

                      {/* Content */}
                      {content && (
                        <div className="message-content" style={{
                          marginLeft: '24px',
                          padding: '10px 12px',
                          backgroundColor: '#f9fafb',
                          borderRadius: '6px',
                          fontSize: '13px',
                          whiteSpace: 'pre-wrap',
                          wordBreak: 'break-word'
                        }}>
                          {content}
                        </div>
                      )}

                      {/* Tool calls */}
                      {toolCalls && Array.isArray(toolCalls) && toolCalls.length > 0 && (
                        <div className="tool-calls" style={{ marginLeft: '24px', marginTop: '8px' }}>
                          {toolCalls.map((call: any, callIdx: number) => (
                            <div key={callIdx} style={{
                              padding: '6px 10px',
                              backgroundColor: '#fffbeb',
                              border: '1px solid #fcd34d',
                              borderRadius: '4px',
                              fontSize: '12px',
                              marginBottom: callIdx < toolCalls.length - 1 ? '4px' : '0'
                            }}>
                              <span style={{ fontWeight: 600 }}>🔧 {call.name || call.function?.name}</span>
                              {call.args && (
                                <pre style={{
                                  margin: '4px 0 0 0',
                                  fontSize: '11px',
                                  whiteSpace: 'pre-wrap',
                                  wordBreak: 'break-word',
                                  color: '#78716c'
                                }}>
                                  {JSON.stringify(call.args, null, 2)}
                                </pre>
                              )}
                            </div>
                          ))}
                        </div>
                      )}
                    </div>
                  );
                });
              })()}
            </div>
          ) : tool.tool_name === 'plan_tasks' ? (
            // plan_tasks type: display TODO list
            <div className="plan-tasks-display">
              {(() => {
                let tasks: string[] = [];

                // Parse raw_input to extract tasks
                if (tool.parameters.raw_input) {
                  try {
                    const parsed = JSON.parse(tool.parameters.raw_input.replace(/'/g, '"'));
                    if (parsed.tasks && Array.isArray(parsed.tasks)) {
                      tasks = parsed.tasks;
                    }
                  } catch {
                    // Try alternative format
                    try {
                      const parsed = eval('(' + tool.parameters.raw_input + ')');
                      if (parsed.tasks && Array.isArray(parsed.tasks)) {
                        tasks = parsed.tasks;
                      }
                    } catch {
                      // Fallback: extract tasks manually
                      const match = tool.parameters.raw_input.match(/tasks['"]?\s*:\s*\[([^\]]+)\]/);
                      if (match) {
                        tasks = match[1].split(',').map((t: string) => t.trim().replace(/^['"]|['"]$/g, ''));
                      }
                    }
                  }
                }

                return (
                  <div className="todo-list">
                    <div style={{ fontWeight: 600, fontSize: '14px', marginBottom: '12px', color: '#374151' }}>
                      📋 TODO List ({tasks.length} tasks)
                    </div>
                    {tasks.length > 0 ? (
                      <ol style={{ margin: 0, paddingLeft: '20px' }}>
                        {tasks.map((task, idx) => (
                          <li key={idx} style={{
                            padding: '8px 12px',
                            marginBottom: idx < tasks.length - 1 ? '8px' : '0',
                            backgroundColor: '#f9fafb',
                            borderRadius: '6px',
                            fontSize: '13px',
                            lineHeight: '1.6',
                            color: '#1f2937'
                          }}>
                            {task}
                          </li>
                        ))}
                      </ol>
                    ) : (
                      <div style={{ padding: '12px', color: '#9ca3af', fontSize: '13px' }}>
                        No tasks found
                      </div>
                    )}
                  </div>
                );
              })()}
            </div>
          ) : tool.tool_name === 'agent_tool' ? (
            // agent_tool type: display context, level, and task details
            <div className="agent-tool-display">
              {(() => {
                let context = '';
                let level = 1;
                let taskDetails: string[] = [];

                // Parse raw_input
                if (tool.parameters.raw_input) {
                  try {
                    // Replace single quotes with double quotes for JSON parsing
                    const normalized = tool.parameters.raw_input.replace(/'/g, '"');
                    const parsed = JSON.parse(normalized);
                    context = parsed.context || '';
                    level = parsed.level || 1;
                    taskDetails = parsed.task_details || [];
                  } catch {
                    // Fallback: try to extract using regex
                    const contextMatch = tool.parameters.raw_input.match(/'context'\s*:\s*'([^']+)'/);
                    if (contextMatch) context = contextMatch[1];

                    const levelMatch = tool.parameters.raw_input.match(/'level'\s*:\s*(\d+)/);
                    if (levelMatch) level = parseInt(levelMatch[1]);

                    const tasksMatch = tool.parameters.raw_input.match(/'task_details'\s*:\s*\[(.*?)\]/);
                    if (tasksMatch) {
                      const tasksStr = tasksMatch[1];
                      taskDetails = tasksStr.split(',').map((t: string) => t.trim().replace(/^['"]|['"]$/g, ''));
                    }
                  }
                }

                return (
                  <div>
                    {/* Context */}
                    {context && (
                      <div style={{ marginBottom: '16px' }}>
                        <div style={{ fontWeight: 600, fontSize: '13px', marginBottom: '8px', color: '#374151' }}>
                          🎯 Context (Level {level})
                        </div>
                        <div style={{
                          padding: '10px 12px',
                          backgroundColor: '#f0fdf4',
                          borderRadius: '6px',
                          border: '1px solid #86efac',
                          fontSize: '13px',
                          lineHeight: '1.6',
                          whiteSpace: 'pre-wrap',
                          wordBreak: 'break-word',
                          color: '#166534'
                        }}>
                          {context}
                        </div>
                      </div>
                    )}

                    {/* Task Details */}
                    {taskDetails.length > 0 && (
                      <div>
                        <div style={{ fontWeight: 600, fontSize: '13px', marginBottom: '8px', color: '#374151' }}>
                          📋 Task Details ({taskDetails.length})
                        </div>
                        <ol style={{ margin: 0, paddingLeft: '20px' }}>
                          {taskDetails.map((task, idx) => (
                            <li key={idx} style={{
                              padding: '8px 12px',
                              marginBottom: idx < taskDetails.length - 1 ? '8px' : '0',
                              backgroundColor: '#eff6ff',
                              borderRadius: '6px',
                              fontSize: '13px',
                              lineHeight: '1.6',
                              color: '#1e3a8a',
                              border: '1px solid #dbeafe'
                            }}>
                              {task}
                            </li>
                          ))}
                        </ol>
                      </div>
                    )}
                  </div>
                );
              })()}
            </div>
          ) : tool.tool_name === 'think_tool' ? (
            // think_tool type: display thought content
            <div className="think-tool-display">
              {(() => {
                let thought = '';

                // Parse raw_input to extract thought
                if (tool.parameters.raw_input) {
                  try {
                    // Replace single quotes with double quotes for JSON parsing
                    const normalized = tool.parameters.raw_input.replace(/'/g, '"');
                    const parsed = JSON.parse(normalized);
                    thought = parsed.thought || '';
                  } catch {
                    // Fallback: try to extract thought using regex
                    const thoughtMatch = tool.parameters.raw_input.match(/'thought'\s*:\s*'([^']+)'/);
                    if (thoughtMatch) {
                      thought = thoughtMatch[1];
                    } else {
                      // Try with double quotes
                      const thoughtMatch2 = tool.parameters.raw_input.match(/"thought"\s*:\s*"([^"]+)"/);
                      if (thoughtMatch2) {
                        thought = thoughtMatch2[1];
                      }
                    }
                  }
                }

                return (
                  <div>
                    <div style={{ fontWeight: 600, fontSize: '13px', marginBottom: '8px', color: '#374151' }}>
                      💭 Thought
                    </div>
                    {thought ? (
                      <div style={{
                        padding: '12px 14px',
                        backgroundColor: '#fef3c7',
                        borderRadius: '8px',
                        border: '1px solid #fcd34d',
                        fontSize: '13px',
                        lineHeight: '1.7',
                        whiteSpace: 'pre-wrap',
                        wordBreak: 'break-word',
                        color: '#78350f',
                        fontStyle: 'italic'
                      }}>
                        {thought}
                      </div>
                    ) : (
                      <div style={{
                        padding: '10px 12px',
                        backgroundColor: '#f9fafb',
                        borderRadius: '6px',
                        fontSize: '12px',
                        color: '#9ca3af',
                        fontStyle: 'italic'
                      }}>
                        No thought content available
                      </div>
                    )}
                  </div>
                );
              })()}
            </div>
          ) : tool.tool_name === 'python_coder_tool' ? (
            // python_coder_tool type: display task description
            <div className="python-coder-tool-display">
              {(() => {
                let taskDescription = '';

                // Parse raw_input to extract task_description
                if (tool.parameters.raw_input) {
                  try {
                    // Replace single quotes with double quotes for JSON parsing
                    const normalized = tool.parameters.raw_input.replace(/'/g, '"');
                    const parsed = JSON.parse(normalized);
                    taskDescription = parsed.task_description || '';
                  } catch {
                    // Fallback: try to extract using regex
                    const taskMatch = tool.parameters.raw_input.match(/'task_description'\s*:\s*'([^']+)'/);
                    if (taskMatch) {
                      taskDescription = taskMatch[1];
                    } else {
                      // Try with double quotes
                      const taskMatch2 = tool.parameters.raw_input.match(/"task_description"\s*:\s*"([^"]+)"/);
                      if (taskMatch2) {
                        taskDescription = taskMatch2[1];
                      }
                    }
                  }
                }

                return (
                  <div>
                    <div style={{ fontWeight: 600, fontSize: '13px', marginBottom: '8px', color: '#374151' }}>
                      🐍 Task Description
                    </div>
                    {taskDescription ? (
                      <div style={{
                        padding: '12px 14px',
                        backgroundColor: '#eff6ff',
                        borderRadius: '8px',
                        border: '1px solid #93c5fd',
                        fontSize: '13px',
                        lineHeight: '1.6',
                        whiteSpace: 'pre-wrap',
                        wordBreak: 'break-word',
                        color: '#1e3a8a'
                      }}>
                        {taskDescription}
                      </div>
                    ) : (
                      <div style={{
                        padding: '10px 12px',
                        backgroundColor: '#f9fafb',
                        borderRadius: '6px',
                        fontSize: '12px',
                        color: '#9ca3af',
                        fontStyle: 'italic'
                      }}>
                        No task description available
                      </div>
                    )}
                  </div>
                );
              })()}
            </div>
          ) : (tool.tool_name === 'nmap_scan' || tool.tool_name === 'command_tool' ||
              (tool.result && (tool.result.stdout !== undefined || tool.result.stderr !== undefined))) ? (
            // command tool type: display command parameters
            <div className="command-tool-display">
              {(() => {
                let params: Record<string, string> = {};

                // Parse raw_input to extract parameters
                if (tool.parameters.raw_input) {
                  try {
                    // Replace single quotes with double quotes for JSON parsing
                    const normalized = tool.parameters.raw_input.replace(/'/g, '"');
                    const parsed = JSON.parse(normalized);
                    params = parsed || {};
                  } catch {
                    // Fallback: try to extract key-value pairs using regex
                    const pairs = tool.parameters.raw_input.match(/'([^']+)'\s*:\s*'([^']*)'/g);
                    if (pairs) {
                      pairs.forEach((pair: string) => {
                        const match = pair.match(/'([^']+)'\s*:\s*'([^']*)'/);
                        if (match) {
                          params[match[1]] = match[2];
                        }
                      });
                    }
                  }
                }

                // Also check for individual parameter fields
                if (tool.parameters.target) params.target = tool.parameters.target;
                if (tool.parameters.ports) params.ports = tool.parameters.ports;
                if (tool.parameters.scan_type) params.scan_type = tool.parameters.scan_type;
                if (tool.parameters.command) params.command = tool.parameters.command;

                return (
                  <div>
                    <div style={{ fontWeight: 600, fontSize: '13px', marginBottom: '8px', color: '#374151' }}>
                      💻 Command Parameters
                    </div>
                    {Object.keys(params).length > 0 ? (
                      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(2, 1fr)', gap: '8px' }}>
                        {Object.entries(params).map(([key, value]) => (
                          <div key={key} style={{
                            padding: '8px 12px',
                            backgroundColor: '#f9fafb',
                            borderRadius: '6px',
                            border: '1px solid #e5e7eb'
                          }}>
                            <div style={{ fontSize: '11px', color: '#6b7280', fontWeight: 600, marginBottom: '4px', textTransform: 'uppercase' }}>
                              {key}
                            </div>
                            <div style={{
                              fontSize: '12px',
                              color: '#1f2937',
                              fontFamily: 'Monaco, Menlo, monospace',
                              wordBreak: 'break-word',
                              backgroundColor: '#f3f4f6',
                              padding: '4px 8px',
                              borderRadius: '4px'
                            }}>
                              {value}
                            </div>
                          </div>
                        ))}
                      </div>
                    ) : (
                      <div style={{
                        padding: '10px 12px',
                        backgroundColor: '#f9fafb',
                        borderRadius: '6px',
                        fontSize: '12px',
                        color: '#9ca3af',
                        fontStyle: 'italic'
                      }}>
                        No parameters available
                      </div>
                    )}
                  </div>
                );
              })()}
            </div>
          ) : (
            // Non-LLM type: display as JSON
            <div className="json-display">
              <pre>{JSON.stringify(tool.parameters, null, 2)}</pre>
            </div>
          )}
        </div>
      )}

      {/* Output Result */}
      {tool && tool.result && Object.keys(tool.result).length > 0 && (
        <div className="detail-section">
          <h4 className="section-title">
            {tool.status === 'completed' ? '✅ Output (Success)' :
             tool.status === 'failed' ? '❌ Output (Failed)' :
             '⏳ Output (Partial)'}
          </h4>
          {tool.result.generations || tool.result.tool_calls || tool.result.llm_output ? (
            // LLM type output
            <div className="llm-output-display">
              {/* LLM Info */}
              {tool.result.llm_output && (
                <div className="llm-info-section" style={{
                  marginBottom: '16px',
                  padding: '12px',
                  backgroundColor: '#f0fdf4',
                  borderRadius: '8px',
                  border: '1px solid #86efac'
                }}>
                  <div style={{ fontWeight: 600, fontSize: '13px', marginBottom: '8px', color: '#166534' }}>
                    🤖 LLM Information
                  </div>
                  <div style={{ display: 'grid', gridTemplateColumns: 'repeat(2, 1fr)', gap: '8px', fontSize: '12px' }}>
                    <div>
                      <span style={{ color: '#6b7280' }}>Model:</span>
                      <span style={{ marginLeft: '8px', fontWeight: 500 }}>{tool.result.llm_output.model_name}</span>
                    </div>
                    <div>
                      <span style={{ color: '#6b7280' }}>Provider:</span>
                      <span style={{ marginLeft: '8px', fontWeight: 500 }}>{tool.result.llm_output.model_provider}</span>
                    </div>
                    {tool.result.llm_output.token_usage && (
                      <>
                        <div>
                          <span style={{ color: '#6b7280' }}>Total Tokens:</span>
                          <span style={{ marginLeft: '8px', fontWeight: 500 }}>{tool.result.llm_output.token_usage.total_tokens}</span>
                        </div>
                        <div>
                          <span style={{ color: '#6b7280' }}>Prompt:</span>
                          <span style={{ marginLeft: '8px', fontWeight: 500 }}>{tool.result.llm_output.token_usage.prompt_tokens}</span>
                        </div>
                        <div>
                          <span style={{ color: '#6b7280' }}>Completion:</span>
                          <span style={{ marginLeft: '8px', fontWeight: 500 }}>{tool.result.llm_output.token_usage.completion_tokens}</span>
                        </div>
                        {tool.result.llm_output.token_usage.reasoning_tokens !== undefined && (
                          <div>
                            <span style={{ color: '#6b7280' }}>Reasoning:</span>
                            <span style={{ marginLeft: '8px', fontWeight: 500 }}>{tool.result.llm_output.token_usage.reasoning_tokens}</span>
                          </div>
                        )}
                      </>
                    )}
                  </div>
                </div>
              )}

              {/* Generations - Text Output */}
              {tool.result.generations && Array.isArray(tool.result.generations) && tool.result.generations.length > 0 && (
                <div className="generations-section" style={{ marginBottom: '16px' }}>
                  <div style={{ fontWeight: 600, fontSize: '13px', marginBottom: '8px', color: '#374151' }}>
                    📝 Generated Text
                  </div>
                  {tool.result.generations.map((gen: any, genIdx: number) => (
                    <div key={genIdx} style={{
                      padding: '12px',
                      backgroundColor: '#fafafa',
                      borderRadius: '6px',
                      marginBottom: genIdx < (tool.result.generations?.length || 0) - 1 ? '8px' : '0'
                    }}>
                      {Array.isArray(gen) ? gen.map((g: any, gIdx: number) => (
                        <div key={gIdx}>
                          {g.text && (
                            <div style={{
                              fontSize: '13px',
                              lineHeight: '1.6',
                              whiteSpace: 'pre-wrap',
                              wordBreak: 'break-word',
                              color: '#1f2937'
                            }}>
                              {g.text}
                            </div>
                          )}
                          {g.generation_info && (
                            <div style={{ marginTop: '8px', fontSize: '11px', color: '#9ca3af' }}>
                              Finish reason: {g.generation_info.finish_reason || 'N/A'}
                            </div>
                          )}
                        </div>
                      )) : (
                        <>
                          {gen.text && (
                            <div style={{
                              fontSize: '13px',
                              lineHeight: '1.6',
                              whiteSpace: 'pre-wrap',
                              wordBreak: 'break-word',
                              color: '#1f2937'
                            }}>
                              {gen.text}
                            </div>
                          )}
                          {gen.generation_info && (
                            <div style={{ marginTop: '8px', fontSize: '11px', color: '#9ca3af' }}>
                              Finish reason: {gen.generation_info.finish_reason || 'N/A'}
                            </div>
                          )}
                        </>
                      )}
                    </div>
                  ))}
                </div>
              )}

              {/* Tool Calls */}
              {tool.result.tool_calls && Array.isArray(tool.result.tool_calls) && tool.result.tool_calls.length > 0 && (
                <div className="tool-calls-section">
                  <div style={{ fontWeight: 600, fontSize: '13px', marginBottom: '8px', color: '#374151' }}>
                    🔧 Tool Calls ({tool.result.tool_calls.length})
                  </div>
                  {tool.result.tool_calls.map((call: any, callIdx: number) => (
                    <div key={callIdx} style={{
                      marginBottom: callIdx < (tool.result.tool_calls?.length || 0) - 1 ? '12px' : '0',
                      padding: '12px',
                      backgroundColor: '#fffbeb',
                      borderRadius: '8px',
                      border: '1px solid #fcd34d'
                    }}>
                      {/* Tool name header */}
                      <div style={{ display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '8px' }}>
                        <span style={{ fontSize: '16px' }}>🔧</span>
                        <span style={{ fontWeight: 600, fontSize: '13px', color: '#92400e' }}>
                          {call.name}
                        </span>
                        {call.type && (
                          <span style={{
                            padding: '2px 6px',
                            backgroundColor: '#fef3c7',
                            borderRadius: '4px',
                            fontSize: '11px',
                            color: '#92400e'
                          }}>
                            {call.type}
                          </span>
                        )}
                      </div>

                      {/* Tool arguments */}
                      {call.args && (
                        <div style={{
                          padding: '8px 10px',
                          backgroundColor: '#fffde7',
                          borderRadius: '4px',
                          border: '1px dashed #fcd34d'
                        }}>
                          <div style={{ fontSize: '11px', fontWeight: 600, color: '#a16207', marginBottom: '4px' }}>
                            Arguments:
                          </div>
                          <pre style={{
                            margin: 0,
                            fontSize: '11px',
                            whiteSpace: 'pre-wrap',
                            wordBreak: 'break-word',
                            color: '#78716c',
                            fontFamily: 'monospace'
                          }}>
                            {JSON.stringify(call.args, null, 2)}
                          </pre>
                        </div>
                      )}

                      {/* Tool ID */}
                      {call.id && (
                        <div style={{ marginTop: '6px', fontSize: '10px', color: '#a16207' }}>
                          ID: {call.id}
                        </div>
                      )}
                    </div>
                  ))}
                </div>
              )}

              {/* Statistics */}
              {(tool.result.tool_call_count !== undefined || tool.result.generation_count !== undefined) && (
                <div style={{
                  marginTop: '12px',
                  padding: '8px 12px',
                  backgroundColor: '#f3f4f6',
                  borderRadius: '6px',
                  fontSize: '12px',
                  display: 'flex',
                  gap: '16px'
                }}>
                  {tool.result.tool_call_count !== undefined && (
                    <span>
                      <span style={{ color: '#6b7280' }}>Tool Calls:</span>
                      <span style={{ marginLeft: '6px', fontWeight: 600, color: '#374151' }}>
                        {tool.result.tool_call_count}
                      </span>
                    </span>
                  )}
                  {tool.result.generation_count !== undefined && (
                    <span>
                      <span style={{ color: '#6b7280' }}>Generations:</span>
                      <span style={{ marginLeft: '6px', fontWeight: 600, color: '#374151' }}>
                        {tool.result.generation_count}
                      </span>
                    </span>
                  )}
                </div>
              )}
            </div>
          ) : tool.tool_name === 'plan_tasks' && tool.result.raw_output ? (
            // plan_tasks output: parse and display TODO list with status
            <div className="plan-tasks-output">
              {(() => {
                const rawOutput = tool.result.raw_output;

                // Parse the output to extract tasks and current task
                const plannedTasks: string[] = [];
                let currentTask: string | null = null;
                let taskCount = 0;

                // Extract task count
                const countMatch = rawOutput.match(/✅\s*(\d+)\s+tasks planned/i);
                if (countMatch) {
                  taskCount = parseInt(countMatch[1]);
                }

                // Extract current task (Started: ...)
                const currentMatch = rawOutput.match(/Started:\s*(.+)/);
                if (currentMatch) {
                  currentTask = currentMatch[1].trim();
                }

                // Extract task list
                const lines = rawOutput.split('\n');
                for (const line of lines) {
                  const match = line.match(/^\s*\d+\.\s+(.+)/);
                  if (match) {
                    plannedTasks.push(match[1].trim());
                  }
                }

                return (
                  <div>
                    {/* Summary */}
                    <div style={{
                      marginBottom: '16px',
                      padding: '10px 12px',
                      backgroundColor: '#ecfdf5',
                      borderRadius: '6px',
                      border: '1px solid #6ee7b7'
                    }}>
                      <div style={{ fontWeight: 600, fontSize: '13px', color: '#059669', marginBottom: '4px' }}>
                        ✅ {taskCount} tasks planned
                      </div>
                      {currentTask && (
                        <div style={{ fontSize: '12px', color: '#047857' }}>
                          ▶️ Currently: {currentTask}
                        </div>
                      )}
                    </div>

                    {/* Task List */}
                    {plannedTasks.length > 0 && (
                      <div>
                        <div style={{ fontWeight: 600, fontSize: '13px', marginBottom: '8px', color: '#374151' }}>
                          📋 Task List
                        </div>
                        <ol style={{ margin: 0, paddingLeft: '20px' }}>
                          {plannedTasks.map((task, idx) => {
                            const isCurrent = currentTask && task === currentTask;
                            return (
                              <li key={idx} style={{
                                padding: '8px 12px',
                                marginBottom: idx < plannedTasks.length - 1 ? '8px' : '0',
                                backgroundColor: isCurrent ? '#dbeafe' : '#f9fafb',
                                borderRadius: '6px',
                                fontSize: '13px',
                                lineHeight: '1.6',
                                color: '#1f2937',
                                border: isCurrent ? '1px solid #3b82f6' : 'none'
                              }}>
                                {task}
                                {isCurrent && (
                                  <span style={{
                                    marginLeft: '8px',
                                    padding: '2px 6px',
                                    backgroundColor: '#3b82f6',
                                    color: 'white',
                                    borderRadius: '4px',
                                    fontSize: '10px',
                                    fontWeight: 600
                                  }}>
                                    RUNNING
                                  </span>
                                )}
                              </li>
                            );
                          })}
                        </ol>
                      </div>
                    )}
                  </div>
                );
              })()}
            </div>
          ) : tool.tool_name === 'agent_tool' && tool.result.raw_output ? (
            // agent_tool output: parse structured result
            <div className="agent-tool-output">
              <SyntaxHighlighter
                language="xml"
                style={vscDarkPlus}
                customStyle={{
                  borderRadius: '8px',
                  fontSize: '12px',
                  maxHeight: '500px',
                  overflow: 'auto'
                }}
                codeTagProps={{
                  style: {
                    whiteSpace: 'pre-wrap',
                    wordBreak: 'break-word',
                    overflowWrap: 'break-word'
                  }
                }}
                wrapLines={true}
                showLineNumbers={true}
              >
                {tool.result.raw_output}
              </SyntaxHighlighter>
            </div>
          ) : tool.tool_name === 'think_tool' ? (
            // think_tool output: typically empty or minimal
            <div className="think-tool-output">
              {(() => {
                const rawOutput = tool.result.raw_output;

                // think_tool usually has empty output
                if (!rawOutput || rawOutput.trim() === '') {
                  return (
                    <div style={{
                      padding: '10px 12px',
                      backgroundColor: '#f9fafb',
                      borderRadius: '6px',
                      fontSize: '12px',
                      color: '#9ca3af',
                      fontStyle: 'italic',
                      display: 'flex',
                      alignItems: 'center',
                      gap: '6px'
                    }}>
                      <span>💭</span>
                      <span>Thought processed - no output generated</span>
                    </div>
                  );
                }

                // If there is output, display it
                return (
                  <div>
                    <div style={{ fontWeight: 600, fontSize: '13px', marginBottom: '8px', color: '#374151' }}>
                      💭 Output
                    </div>
                    <div style={{
                      padding: '10px 12px',
                      backgroundColor: '#f9fafb',
                      borderRadius: '6px',
                      fontSize: '13px',
                      lineHeight: '1.6',
                      whiteSpace: 'pre-wrap',
                      wordBreak: 'break-word',
                      color: '#374151'
                    }}>
                      {rawOutput}
                    </div>
                  </div>
                );
              })()}
            </div>
          ) : tool.tool_name === 'python_coder_tool' ? (
            // python_coder_tool output: display code, output, error, iterations
            <div className="python-coder-tool-output">
              {(() => {
                const result = tool.result;
                const code = result.code || '';
                const output = result.output || '';
                const error = result.error;
                const success = result.success;
                const iterations = result.iterations || 0;
                const totalTime = result.total_time_ms;
                const iterationLogs = result.iteration_logs || [];
                const terminationReason = result.termination_reason;

                return (
                  <div>
                    {/* Status Badge */}
                    <div style={{ marginBottom: '16px', display: 'flex', alignItems: 'center', gap: '12px' }}>
                      <div style={{
                        padding: '6px 12px',
                        borderRadius: '6px',
                        fontSize: '12px',
                        fontWeight: 600,
                        backgroundColor: success ? '#d1fae5' : '#fee2e2',
                        color: success ? '#065f46' : '#991b1b',
                        border: success ? '1px solid #86efac' : '1px solid #fca5a5'
                      }}>
                        {success ? '✅ Success' : '❌ Failed'}
                      </div>
                      {iterations !== undefined && (
                        <div style={{ fontSize: '12px', color: '#6b7280' }}>
                          Iterations: <strong>{iterations}</strong>
                        </div>
                      )}
                      {totalTime !== undefined && (
                        <div style={{ fontSize: '12px', color: '#6b7280' }}>
                          Time: <strong>{(totalTime / 1000).toFixed(2)}s</strong>
                        </div>
                      )}
                      {terminationReason && (
                        <div style={{ fontSize: '12px', color: '#6b7280' }}>
                          Reason: <strong>{terminationReason}</strong>
                        </div>
                      )}
                    </div>

                    {/* Code Section */}
                    {code && (
                      <div style={{ marginBottom: '16px' }}>
                        <div style={{ fontWeight: 600, fontSize: '13px', marginBottom: '8px', color: '#374151' }}>
                          🐍 Generated Code
                        </div>
                        <SyntaxHighlighter
                          language="python"
                          style={vscDarkPlus}
                          customStyle={{
                            borderRadius: '8px',
                            fontSize: '12px',
                            maxHeight: '400px'
                          }}
                          wrapLongLines={true}
                          showLineNumbers={true}
                        >
                          {code}
                        </SyntaxHighlighter>
                      </div>
                    )}

                    {/* Output Section */}
                    {output && (
                      <div style={{ marginBottom: '16px' }}>
                        <div style={{ fontWeight: 600, fontSize: '13px', marginBottom: '8px', color: '#374151' }}>
                          📤 Execution Output
                        </div>
                        <div style={{
                          padding: '12px',
                          backgroundColor: '#f9fafb',
                          borderRadius: '6px',
                          border: '1px solid #e5e7eb',
                          fontSize: '12px',
                          lineHeight: '1.5',
                          whiteSpace: 'pre-wrap',
                          wordBreak: 'break-word',
                          color: '#374151',
                          maxHeight: '300px',
                          overflow: 'auto'
                        }}>
                          {output}
                        </div>
                      </div>
                    )}

                    {/* Error Section */}
                    {error && (
                      <div style={{ marginBottom: '16px' }}>
                        <div style={{ fontWeight: 600, fontSize: '13px', marginBottom: '8px', color: '#dc2626' }}>
                          ⚠️ Error
                        </div>
                        <div style={{
                          padding: '12px',
                          backgroundColor: '#fee2e2',
                          borderRadius: '6px',
                          border: '1px solid #fca5a5',
                          fontSize: '12px',
                          lineHeight: '1.5',
                          whiteSpace: 'pre-wrap',
                          wordBreak: 'break-word',
                          color: '#991b1b'
                        }}>
                          {error}
                        </div>
                      </div>
                    )}

                    {/* Iteration Logs */}
                    {iterationLogs.length > 0 && (
                      <div>
                        <div style={{ fontWeight: 600, fontSize: '13px', marginBottom: '8px', color: '#374151' }}>
                          📊 Iteration Logs
                        </div>
                        <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
                          {iterationLogs.map((log: any, idx: number) => (
                            <div key={idx} style={{
                              padding: '10px 12px',
                              backgroundColor: log.result === 'success' ? '#f0fdf4' : '#fef2f2',
                              borderRadius: '6px',
                              border: log.result === 'success' ? '1px solid #86efac' : '1px solid #fca5a5',
                              fontSize: '12px'
                            }}>
                              <div style={{ display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '6px' }}>
                                <span style={{
                                  padding: '2px 8px',
                                  borderRadius: '4px',
                                  backgroundColor: log.result === 'success' ? '#dcfce7' : '#fee2e2',
                                  color: log.result === 'success' ? '#166534' : '#991b1b',
                                  fontSize: '11px',
                                  fontWeight: 600
                                }}>
                                  Iteration {log.iteration}
                                </span>
                                <span style={{
                                  padding: '2px 8px',
                                  borderRadius: '4px',
                                  backgroundColor: '#e5e7eb',
                                  color: '#374151',
                                  fontSize: '10px',
                                  fontWeight: 600
                                }}>
                                  {log.action}
                                </span>
                                {log.execution_time_ms && (
                                  <span style={{ fontSize: '11px', color: '#6b7280', marginLeft: 'auto' }}>
                                    {(log.execution_time_ms / 1000).toFixed(2)}s
                                  </span>
                                )}
                              </div>
                              {log.error_message && (
                                <div style={{
                                  marginTop: '6px',
                                  padding: '6px 8px',
                                  backgroundColor: '#fee2e2',
                                  borderRadius: '4px',
                                  fontSize: '11px',
                                  color: '#991b1b',
                                  whiteSpace: 'pre-wrap'
                                }}>
                                  {log.error_message}
                                </div>
                              )}
                            </div>
                          ))}
                        </div>
                      </div>
                    )}
                  </div>
                );
              })()}
            </div>
          ) : (tool.result && (tool.result.stdout !== undefined || tool.result.stderr !== undefined)) ? (
            // command tool output: display stdout, stderr, return code
            <div className="command-tool-output">
              {(() => {
                const result = tool.result;
                const stdout = result.stdout || '';
                const stderr = result.stderr || '';
                const success = result.success;
                const returnCode = result.return_code;
                const rawOutput = result.raw_output || '';

                // Check if there's an error (validation error or exception)
                if (rawOutput && (!stdout || rawOutput.includes('validation error'))) {
                  return (
                    <div>
                      <div style={{ marginBottom: '16px', display: 'flex', alignItems: 'center', gap: '12px' }}>
                        <div style={{
                          padding: '6px 12px',
                          borderRadius: '6px',
                          fontSize: '12px',
                          fontWeight: 600,
                          backgroundColor: '#fee2e2',
                          color: '#991b1b',
                          border: '1px solid #fca5a5'
                        }}>
                          ❌ Error
                        </div>
                      </div>
                      <div style={{
                        padding: '12px',
                        backgroundColor: '#fef2f2',
                        borderRadius: '6px',
                        border: '1px solid #fca5a5'
                      }}>
                        <div style={{ fontWeight: 600, fontSize: '13px', marginBottom: '8px', color: '#991b1b' }}>
                          📋 Error Output
                        </div>
                        <pre style={{
                          margin: 0,
                          fontSize: '12px',
                          lineHeight: '1.5',
                          whiteSpace: 'pre-wrap',
                          wordBreak: 'break-word',
                          color: '#7f1d1d',
                          fontFamily: 'Monaco, Menlo, monospace'
                        }}>
                          {rawOutput}
                        </pre>
                      </div>
                    </div>
                  );
                }

                return (
                  <div>
                    {/* Status Badge */}
                    <div style={{ marginBottom: '16px', display: 'flex', alignItems: 'center', gap: '12px' }}>
                      <div style={{
                        padding: '6px 12px',
                        borderRadius: '6px',
                        fontSize: '12px',
                        fontWeight: 600,
                        backgroundColor: success !== false ? '#d1fae5' : '#fee2e2',
                        color: success !== false ? '#065f46' : '#991b1b',
                        border: success !== false ? '1px solid #86efac' : '1px solid #fca5a5'
                      }}>
                        {success !== false ? '✅ Success' : '❌ Failed'}
                      </div>
                      {returnCode !== undefined && (
                        <div style={{ fontSize: '12px', color: '#6b7280' }}>
                          Exit Code: <strong style={{
                            color: returnCode === 0 ? '#059669' : '#dc2626'
                          }}>{returnCode}</strong>
                        </div>
                      )}
                    </div>

                    {/* Stdout */}
                    {stdout && (
                      <div style={{ marginBottom: stderr ? '16px' : '0' }}>
                        <div style={{ fontWeight: 600, fontSize: '13px', marginBottom: '8px', color: '#374151' }}>
                          📤 Standard Output
                        </div>
                        <div style={{
                          padding: '12px',
                          backgroundColor: '#1e1e1e',
                          borderRadius: '8px',
                          border: '1px solid #3e4451',
                          overflow: 'auto',
                          maxHeight: '400px'
                        }}>
                          <pre style={{
                            margin: 0,
                            fontSize: '11px',
                            lineHeight: '1.6',
                            fontFamily: 'Monaco, Menlo, "Ubuntu Mono", monospace',
                            color: '#d4d4d4',
                            whiteSpace: 'pre-wrap',
                            wordBreak: 'break-word'
                          }}>
                            {stdout}
                          </pre>
                        </div>
                      </div>
                    )}

                    {/* Stderr */}
                    {stderr && (
                      <div>
                        <div style={{ fontWeight: 600, fontSize: '13px', marginBottom: '8px', color: '#dc2626' }}>
                          ⚠️ Standard Error
                        </div>
                        <div style={{
                          padding: '12px',
                          backgroundColor: '#fef2f2',
                          borderRadius: '6px',
                          border: '1px solid #fca5a5',
                          overflow: 'auto',
                          maxHeight: '200px'
                        }}>
                          <pre style={{
                            margin: 0,
                            fontSize: '11px',
                            lineHeight: '1.5',
                            fontFamily: 'Monaco, Menlo, monospace',
                            color: '#991b1b',
                            whiteSpace: 'pre-wrap',
                            wordBreak: 'break-word'
                          }}>
                            {stderr}
                          </pre>
                        </div>
                      </div>
                    )}

                    {/* No output */}
                    {!stdout && !stderr && !rawOutput && (
                      <div style={{
                        padding: '10px 12px',
                        backgroundColor: '#f9fafb',
                        borderRadius: '6px',
                        fontSize: '12px',
                        color: '#9ca3af',
                        fontStyle: 'italic'
                      }}>
                        No output available
                      </div>
                    )}
                  </div>
                );
              })()}
            </div>
          ) : (
            // Non-LLM, non-plan_tasks, non-agent_tool, non-think_tool, non-python_coder_tool, non-command-output type output: display as JSON
            <div className="json-display">
              <pre>{JSON.stringify(tool.result, null, 2)}</pre>
            </div>
          )}
        </div>
      )}

      {/* Tool-specific: Agent Tool Badge */}
      {tool && tool.is_agent_tool && (
        <div className="detail-section">
          <div className="agent-tool-notice">
            🤖 This tool spawns child agent(s)
          </div>
        </div>
      )}

      {/* Error Message */}
      {item.error_message && (
        <div className="detail-section error-section">
          <h4 className="section-title">⚠️ Error</h4>
          <div className="error-message">
            {item.error_message}
          </div>
        </div>
      )}

      {/* Agent-specific: Success Rate */}
      {isAgent && agent!.success_rate !== undefined && (
        <div className="detail-section">
          <h4 className="section-title">📊 Success Rate</h4>
          <div className="success-rate">
            <div className="success-rate-bar">
              <div 
                className="success-rate-fill" 
                style={{ width: `${agent!.success_rate}%` }}
              />
            </div>
            <span className="success-rate-text">{agent!.success_rate}%</span>
          </div>
        </div>
      )}

      {/* Footer with indicator */}
      <div className="detail-panel-footer">
        <span className="footer-text">End of Details</span>
      </div>
    </div>
  );
};

ExecutionItemDetailPanel.displayName = 'ExecutionItemDetailPanel';
