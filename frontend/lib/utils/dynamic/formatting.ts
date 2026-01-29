/**
 * Formatting utilities
 * Helper functions for formatting messages and content
 */

/**
 * Format timestamp to readable string
 * Shows full date and time in 24-hour format
 */
export const formatTimestamp = (timestamp: number): string => {
  const date = new Date(timestamp);

  // Format: YYYY-MM-DD HH:mm:ss
  const year = date.getFullYear();
  const month = String(date.getMonth() + 1).padStart(2, '0');
  const day = String(date.getDate()).padStart(2, '0');
  const hours = String(date.getHours()).padStart(2, '0');
  const minutes = String(date.getMinutes()).padStart(2, '0');
  const seconds = String(date.getSeconds()).padStart(2, '0');

  return `${year}-${month}-${day} ${hours}:${minutes}:${seconds}`;
};

/**
 * Format duration in milliseconds to readable string
 */
export const formatDuration = (ms: number): string => {
  if (ms < 1000) {
    return `${Math.round(ms)}ms`;
  } else if (ms < 60000) {
    // Less than 1 minute: show seconds
    return `${(ms / 1000).toFixed(2)}s`;
  } else if (ms < 3600000) {
    // Less than 1 hour: show minutes and seconds
    const minutes = Math.floor(ms / 60000);
    const seconds = ((ms % 60000) / 1000).toFixed(0);
    return `${minutes}m ${seconds}s`;
  } else {
    // 1 hour or more: show hours, minutes, and seconds
    const hours = Math.floor(ms / 3600000);
    const minutes = Math.floor((ms % 3600000) / 60000);
    const seconds = ((ms % 60000) / 1000).toFixed(0);
    return `${hours}h ${minutes}m ${seconds}s`;
  }
};

/**
 * Format JSON object to readable string
 */
export const formatJSON = (obj: any, indent: number = 2): string => {
  return JSON.stringify(obj, null, indent);
};
