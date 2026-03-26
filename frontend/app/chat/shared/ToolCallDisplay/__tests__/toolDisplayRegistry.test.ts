import { describe, expect, it } from 'vitest'

import { formatToolDisplay } from '../toolDisplayRegistry'

describe('formatToolDisplay', () => {
  it('labels preview_skill as previewing and shows the skill name', () => {
    const display = formatToolDisplay('preview_skill', {
      skill_name: 'network-scan',
      skills_subdir: 'thread-123/skills',
    })

    expect(display).toEqual({
      label: 'Previewing skill: network-scan',
      detail: 'thread-123/skills',
    })
  })
})
