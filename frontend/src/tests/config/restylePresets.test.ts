import { describe, expect, it } from 'vitest'

import { GENERATE_PRESETS } from '@/config/generatePresets'
import { getRestylePresetById } from '@/config/restylePresets'
import { TRANSLATE_PRESETS } from '@/config/translatePresets'

describe('restyle presets', () => {
  it('maps legacy DDI restyle id to the canonical backend preset metadata', () => {
    const preset = getRestylePresetById('ddi-restyle-v2')

    expect(preset).toBeDefined()
    expect(preset?.id).toBe('ddi-standard')
    expect(preset?.legacyIds).toContain('ddi-restyle-v2')
    expect(preset?.imageUrl).toBe('/api/presets/ddi-standard/image')
    expect(preset?.sha256).toBe('f7f14464afd72793df3b68e5c06a91a32b4329c24d0886a7a557dd01bdcc112c')
    expect(preset?.prompt).toContain('零重写内容原则')
    expect(preset?.imageUrl).not.toContain('/restyle-presets/')
  })

  it('uses one canonical DDI preset id and backend image URL across runtime flows', () => {
    const restyle = getRestylePresetById('ddi-standard')
    const generate = GENERATE_PRESETS.find((preset) => preset.id === 'ddi-standard')
    const translateRestyle = TRANSLATE_PRESETS.find((preset) => preset.id === 'translation-restyle')

    expect(restyle?.id).toBe('ddi-standard')
    expect(generate?.id).toBe('ddi-standard')
    expect(translateRestyle?.stylePresetId).toBe('ddi-standard')
    expect(restyle?.imageUrl).toBe(generate?.imageUrl)
    expect(generate?.imageUrl).toBe('/api/presets/ddi-standard/image')
  })
})
