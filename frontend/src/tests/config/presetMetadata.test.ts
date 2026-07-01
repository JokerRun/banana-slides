import { beforeEach, describe, expect, it, vi } from 'vitest'

import { clearRuntimePresetCache, getRuntimePresetById, loadRuntimePresets } from '@/config/presetMetadata'
import { TRANSLATION_WITH_RESTYLE_PROMPT } from '@/config/translatePresets'
import { listPresets } from '@/api/endpoints'

vi.mock('@/api/endpoints', () => ({
  listPresets: vi.fn(),
}))

describe('preset metadata runtime loader', () => {
  beforeEach(() => {
    clearRuntimePresetCache()
    vi.clearAllMocks()
  })

  it('uses backend /api/presets as authoritative metadata', async () => {
    vi.mocked(listPresets).mockResolvedValue({
      data: {
        presets: [{
          id: 'ddi-standard',
          legacyIds: ['ddi-restyle-v2'],
          version: '2026-07-01',
          name: 'DDI Standard',
          baseImage: 'base.png',
          sha256: 'abc123',
          imageUrl: '/api/presets/ddi-standard/image',
          prompts: {
            generate: 'from-api-generate',
            restyle: 'from-api-restyle',
            translateRestyle: 'from-api-translate',
          },
        }],
      },
    })

    const preset = await getRuntimePresetById('ddi-restyle-v2')

    expect(listPresets).toHaveBeenCalled()
    expect(preset?.id).toBe('ddi-standard')
    expect(preset?.sha256).toBe('abc123')
    expect(preset?.imageUrl).toBe('/api/presets/ddi-standard/image')
    expect(preset?.prompts.restyle).toBe('from-api-restyle')
  })

  it('falls back to local TS metadata when API fails', async () => {
    vi.mocked(listPresets).mockRejectedValue(new Error('offline'))

    const presets = await loadRuntimePresets()

    expect(presets.length).toBeGreaterThan(0)
    expect(presets[0]?.imageUrl).toBe('/api/presets/ddi-standard/image')
    expect(presets[0]?.prompts.translateRestyle).toBe(TRANSLATION_WITH_RESTYLE_PROMPT)
    expect(presets[0]?.prompts.translateRestyle).not.toBe(presets[0]?.prompts.restyle)
  })
})