import { describe, expect, it } from 'vitest'

import { getRestylePresetById } from '@/config/restylePresets'

describe('restyle presets', () => {
  it('uses the product-provided DDI restyle prompt without changing the base image', () => {
    const preset = getRestylePresetById('ddi-restyle-v2')

    expect(preset).toBeDefined()
    expect(preset?.styleRefImageUrl).toBe('/restyle-presets/ddi-base-v2.png')
    expect(preset?.prompt).toContain('ROLE: THE ARCHITECT')
    expect(preset?.prompt).toContain('BASE TEMPLATE LOCK')
    expect(preset?.prompt).toContain('Font size: EXACTLY 32pt')
    expect(preset?.prompt).toContain('DDI Slate Blue #3D4F5F')
    expect(preset?.prompt).toContain('KEY CONTENT: Analyze text, data, and charts from the original PPT slide image')
    expect(preset?.prompt).not.toContain('KEY CONTENT: Analyze text, data, and charts from IMAGE 1')
    expect(preset?.prompt).not.toContain('字号：24pt')
  })
})
