/**
 * Shared tool display registry.
 * Maps raw tool names + args to user-friendly labels and details.
 */

function basename(path: string): string {
  return path.split('/').pop() || path
}

function shortenPath(path: string, maxLen = 40): string {
  if (path.length <= maxLen) return path
  const name = basename(path)
  if (name.length >= maxLen - 4) return `.../${name}`
  const budget = maxLen - name.length - 4
  return path.slice(0, budget) + '.../' + name
}

export interface ToolDisplay {
  label: string
  detail: string
}

export function formatToolDisplay(toolName: string, toolInput: Record<string, any>): ToolDisplay {
  if (toolName === 'read_file' || toolName === 'read') {
    const path = toolInput?.file_path || toolInput?.path || ''
    return { label: `Reading ${basename(path)}`, detail: path ? shortenPath(path) : '' }
  }

  if (toolName === 'write_file' || toolName === 'write' || toolName === 'create_file') {
    const path = toolInput?.file_path || toolInput?.path || ''
    return { label: `Writing ${basename(path)}`, detail: path ? shortenPath(path) : '' }
  }

  if (toolName === 'edit_file' || toolName === 'edit' || toolName === 'str_replace_editor') {
    const path = toolInput?.file_path || toolInput?.path || ''
    return { label: `Editing ${basename(path)}`, detail: path ? shortenPath(path) : '' }
  }

  if (toolName === 'execute' || toolName === 'bash' || toolName === 'run_command') {
    const cmd = toolInput?.command || toolInput?.code || ''
    const shortCmd = typeof cmd === 'string' ? cmd.slice(0, 60) : ''
    return { label: 'Executing command', detail: shortCmd ? (shortCmd.length < cmd.length ? shortCmd + '...' : shortCmd) : '' }
  }

  if (toolName === 'python' || toolName === 'python_interpreter') {
    const code = toolInput?.code || ''
    const firstLine = typeof code === 'string' ? code.split('\n')[0].slice(0, 50) : ''
    return { label: 'Running Python', detail: firstLine || '' }
  }

  if (toolName === 'preview_skill') {
    const skillName = toolInput?.skill_name || ''
    const skillsSubdir = toolInput?.skills_subdir || ''
    return {
      label: `Previewing skill${skillName ? ': ' + skillName : ''}`,
      detail: typeof skillsSubdir === 'string' ? skillsSubdir : '',
    }
  }

  if (toolName === 'glob' || toolName === 'find_files') {
    const pattern = toolInput?.pattern || ''
    return { label: 'Searching files', detail: pattern || '' }
  }

  if (toolName === 'grep' || toolName === 'search') {
    const pattern = toolInput?.pattern || toolInput?.query || ''
    return { label: 'Searching content', detail: pattern || '' }
  }

  if (toolName === 'ls' || toolName === 'list_directory') {
    const path = toolInput?.path || ''
    return { label: `Listing ${basename(path) || 'directory'}`, detail: path ? shortenPath(path) : '' }
  }

  if (toolName === 'write_todos' || toolName === 'todo_write') {
    return { label: 'Updating plan', detail: '' }
  }

  if (toolName === 'think' || toolName === 'reasoning') {
    return { label: 'Thinking...', detail: '' }
  }

  if (toolName === 'web_search') {
    const query = toolInput?.query || ''
    return { label: 'Web search', detail: query ? query.slice(0, 50) : '' }
  }

  if (toolName === 'planner') {
    return { label: 'Planning', detail: '' }
  }

  const readableName = toolName
    .replace(/_/g, ' ')
    .replace(/-/g, ' ')
    .replace(/\b\w/g, (c) => c.toUpperCase())
  return { label: readableName, detail: '' }
}
