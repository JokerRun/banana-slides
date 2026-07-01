import { describe, expect, it } from 'vitest'

import { getProjectTitle } from '@/utils/projectUtils'
import type { Project } from '@/types'

const makeProject = (
  overrides: Partial<Project> & { project_name?: string | null } = {}
): Project & { project_name?: string | null } => ({
  project_id: 'project-1',
  idea_prompt: 'source-file.pptx',
  creation_type: 'descriptions',
  status: 'COMPLETED',
  pages: [
    {
      page_id: 'page-1',
      order_index: 0,
      outline_content: { title: '第一页标题', points: [] },
      status: 'COMPLETED',
    },
  ],
  created_at: '2026-07-01T00:00:00Z',
  updated_at: '2026-07-01T00:00:00Z',
  ...overrides,
})

describe('getProjectTitle', () => {
  it('uses explicit project_name before first page title for descriptions projects', () => {
    const project = makeProject({ project_name: '  重命名后的项目  ' })

    expect(getProjectTitle(project)).toBe('重命名后的项目')
  })

  it('keeps first page title fallback for descriptions projects without project_name', () => {
    const project = makeProject({ project_name: null })

    expect(getProjectTitle(project)).toBe('第一页标题')
  })

  it('uses idea_prompt as source filename fallback for translate and restyle projects', () => {
    expect(getProjectTitle(makeProject({ creation_type: 'translate' }))).toBe('source-file.pptx')
    expect(getProjectTitle(makeProject({ creation_type: 'restyle' }))).toBe('source-file.pptx')
  })

  it('uses explicit project_name before source filename for translate and restyle projects', () => {
    expect(getProjectTitle(makeProject({
      creation_type: 'translate',
      project_name: '翻译项目名称',
    }))).toBe('翻译项目名称')
    expect(getProjectTitle(makeProject({
      creation_type: 'restyle',
      project_name: 'Restyle 项目名称',
    }))).toBe('Restyle 项目名称')
  })
})
