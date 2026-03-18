/**
 * Format tool calls for friendly display in the Skill Creator chat.
 *
 * - File operations → show the file path
 * - Tool calls → show what tool was executed with key args
 */

/** Extract just the filename from a path */
function basename(path: string): string {
  return path.split('/').pop() || path
}

/** Shorten a path for display if it's long */
function shortenPath(path: string, maxLen = 40): string {
  if (path.length <= maxLen) return path
  const name = basename(path)
  if (name.length >= maxLen - 4) return `.../${name}`
  const budget = maxLen - name.length - 4
  return path.slice(0, budget) + '.../' + name
}

interface ToolDisplay {
  /** Short label shown as the tool badge (e.g. "Writing SKILL.md") */
  label: string
  /** Optional detail line (e.g. the full file path) */
  detail: string
}

/**
 * Map a raw tool name + its input args to a user-friendly label and detail.
 */
export function formatToolDisplay(
  toolName: string,
  toolInput: Record<string, any>
): ToolDisplay {
  // --- File read operations ---
  if (toolName === 'read_file' || toolName === 'read') {
    const path = toolInput?.file_path || toolInput?.path || ''
    return {
      label: `Reading ${basename(path)}`,
      detail: path ? shortenPath(path) : '',
    }
  }

  // --- File write operations ---
  if (toolName === 'write_file' || toolName === 'write' || toolName === 'create_file') {
    const path = toolInput?.file_path || toolInput?.path || ''
    return {
      label: `Writing ${basename(path)}`,
      detail: path ? shortenPath(path) : '',
    }
  }

  // --- File edit operations ---
  if (toolName === 'edit_file' || toolName === 'edit' || toolName === 'str_replace_editor') {
    const path = toolInput?.file_path || toolInput?.path || ''
    return {
      label: `Editing ${basename(path)}`,
      detail: path ? shortenPath(path) : '',
    }
  }

  // --- Shell/execute ---
  if (toolName === 'execute' || toolName === 'bash' || toolName === 'run_command') {
    const cmd = toolInput?.command || toolInput?.code || ''
    const shortCmd = typeof cmd === 'string' ? cmd.slice(0, 60) : ''
    return {
      label: 'Executing command',
      detail: shortCmd ? (shortCmd.length < cmd.length ? shortCmd + '...' : shortCmd) : '',
    }
  }

  // --- Python execution (CodeAgent) ---
  if (toolName === 'python' || toolName === 'python_interpreter') {
    const code = toolInput?.code || ''
    const firstLine = typeof code === 'string' ? code.split('\n')[0].slice(0, 50) : ''
    return {
      label: 'Running Python',
      detail: firstLine || '',
    }
  }

  // --- Skill-specific tools ---
  if (toolName === 'preview_skill') {
    const skillName = toolInput?.skill_name || ''
    return {
      label: `Previewing skill${skillName ? ': ' + skillName : ''}`,
      detail: '',
    }
  }

  if (toolName === 'deploy_local_skill') {
    const skillName = toolInput?.skill_name || ''
    return {
      label: `Deploying skill${skillName ? ': ' + skillName : ''}`,
      detail: '',
    }
  }

  // --- Glob/search ---
  if (toolName === 'glob' || toolName === 'find_files') {
    const pattern = toolInput?.pattern || ''
    return {
      label: 'Searching files',
      detail: pattern || '',
    }
  }

  if (toolName === 'grep' || toolName === 'search') {
    const pattern = toolInput?.pattern || toolInput?.query || ''
    return {
      label: 'Searching content',
      detail: pattern || '',
    }
  }

  // --- List directory ---
  if (toolName === 'ls' || toolName === 'list_directory') {
    const path = toolInput?.path || ''
    return {
      label: `Listing ${basename(path) || 'directory'}`,
      detail: path ? shortenPath(path) : '',
    }
  }

  // --- Todo/planning ---
  if (toolName === 'write_todos' || toolName === 'todo_write') {
    return {
      label: 'Updating plan',
      detail: '',
    }
  }

  if (toolName === 'think' || toolName === 'reasoning') {
    return {
      label: 'Thinking...',
      detail: '',
    }
  }

  // --- Fallback: show raw tool name in readable form ---
  const readableName = toolName
    .replace(/_/g, ' ')
    .replace(/-/g, ' ')
    .replace(/\b\w/g, (c) => c.toUpperCase())

  return {
    label: readableName,
    detail: '',
  }
}
