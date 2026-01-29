/**
 * Tooltip component
 * Displays tooltip on hover
 */

import React from 'react';

interface TooltipProps {
  content: string;
  children: React.ReactNode;
}

export const Tooltip: React.FC<TooltipProps> = ({ content, children }) => {
  return (
    <div className="tooltip">
      {children}
      <div className="tooltip-text">{content}</div>
    </div>
  );
};

Tooltip.displayName = 'Tooltip';
