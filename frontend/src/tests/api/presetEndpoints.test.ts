import { beforeEach, describe, expect, it, vi } from 'vitest'

import { createRestyleProject, createTranslateProject, listPresets } from '@/api/endpoints'
import { apiClient } from '@/api/client'

vi.mock('@/api/client', () => ({
  apiClient: {
    get: vi.fn(),
    post: vi.fn(),
  },
}))

describe('preset endpoints', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('lists backend presets', async () => {
    vi.mocked(apiClient.get).mockResolvedValue({ data: { data: { presets: [] } } })

    await listPresets()

    expect(apiClient.get).toHaveBeenCalledWith('/api/presets')
  })

  it('creates restyle project with only a preset id and no uploaded style_refs', async () => {
    vi.mocked(apiClient.post).mockResolvedValue({ data: { data: { project_id: 'p1' } } })

    await createRestyleProject(
      new File(['ppt'], 'slides.pptx'),
      [],
      { stylePresetId: 'ddi-standard', restylePrompt: 'prompt' }
    )

    const formData = vi.mocked(apiClient.post).mock.calls[0][1] as FormData
    expect(apiClient.post).toHaveBeenCalledWith('/api/projects/restyle', expect.any(FormData))
    expect(formData.get('style_preset_id')).toBe('ddi-standard')
    expect(formData.getAll('style_refs')).toEqual([])
  })

  it('creates translate restyle project with only a preset id and no uploaded style_refs', async () => {
    vi.mocked(apiClient.post).mockResolvedValue({ data: { data: { project_id: 'p1' } } })

    await createTranslateProject(
      new File(['ppt'], 'slides.pptx'),
      {
        targetLanguage: 'English',
        translateMode: 'restyle',
        stylePresetId: 'ddi-standard',
      }
    )

    const formData = vi.mocked(apiClient.post).mock.calls[0][1] as FormData
    expect(apiClient.post).toHaveBeenCalledWith('/api/projects/translate', expect.any(FormData))
    expect(formData.get('style_preset_id')).toBe('ddi-standard')
    expect(formData.getAll('style_refs')).toEqual([])
  })
})
