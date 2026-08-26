import { fireEvent, render } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

import { parseSkillFileId } from '@/types/entity-id'

import { SkillWorkspace } from './skill-workspace'

const FILE_ID = parseSkillFileId('sklfile_018f6f42-0a51-7cc4-98c8-4f6f0ca5f001')

describe('SkillWorkspace', () => {
  it('emits a typed file move source when a file is dropped on the root', () => {
    const onMove = vi.fn()
    const data = new Map<string, string>()
    const dataTransfer = {
      effectAllowed: 'none',
      dropEffect: 'none',
      setData: (type: string, value: string) => data.set(type, value),
      getData: (type: string) => data.get(type) ?? '',
    }
    const { getByText } = render(
      <SkillWorkspace
        skillName="Example"
        files={[{ id: FILE_ID, path: 'src/', file_name: 'main.py', size: 10 }]}
        selectedFileId={null}
        canEdit
        onSelectFile={vi.fn()}
        onSelectMain={vi.fn()}
        onAddFolder={vi.fn()}
        onAddToFolder={vi.fn()}
        onDeleteFile={vi.fn()}
        onDeleteFolder={vi.fn()}
        onMove={onMove}
        isMainSelected
      />,
    )

    fireEvent.dragStart(getByText('main.py').closest('div')!, { dataTransfer })
    fireEvent.drop(getByText('Example').closest('div')!.parentElement!, { dataTransfer })

    expect(onMove).toHaveBeenCalledWith({ kind: 'file', fileKey: FILE_ID, path: 'src/' }, '')
  })
})
