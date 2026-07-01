import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { Home } from '@/pages/Home'
import { createTranslateProject } from '@/api/endpoints'

vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    i18n: {
      language: 'zh',
      changeLanguage: vi.fn(),
    },
    t: (key: string) => key,
  }),
}))

vi.mock('@/store/useProjectStore', () => ({
  useProjectStore: () => ({
    initializeProject: vi.fn(),
    isGlobalLoading: false,
  }),
}))

vi.mock('@/api/endpoints', () => ({
  getAuthMe: vi.fn().mockResolvedValue({ data: { user: { id: 'user-1', display_name: 'Captain' } } }),
  logoutAuth: vi.fn().mockResolvedValue({ data: { ok: true } }),
  createRestyleProject: vi.fn(),
  createTranslateProject: vi.fn(),
  uploadReferenceFile: vi.fn(),
  associateFileToProject: vi.fn(),
  triggerFileParse: vi.fn(),
  associateMaterialsToProject: vi.fn(),
}))

describe('Home translate workflow', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    vi.mocked(createTranslateProject).mockResolvedValue({
      data: {
        project_id: 'translate-project-1',
        creation_type: 'translate',
        status: 'SLIDES_EXTRACTED',
        translate_mode: 'restyle',
        target_language: 'English',
        pages: [],
        total_pages: 0,
      },
    })
    URL.createObjectURL = vi.fn(() => 'blob:style-ref')
  })

  it('uses the default DDI restyle preset for translation restyle mode', async () => {
    const { container } = render(
      <MemoryRouter>
        <Home />
      </MemoryRouter>
    )

    fireEvent.click(screen.getByText('多语言翻译'))

    const sourceInput = container.querySelector('input[accept=".pptx,.ppt,.pdf"]')
    expect(sourceInput).toBeInstanceOf(HTMLInputElement)
    fireEvent.change(sourceInput as HTMLInputElement, {
      target: {
        files: [new File(['ppt'], 'source.pptx', { type: 'application/vnd.openxmlformats-officedocument.presentationml.presentation' })],
      },
    })

    fireEvent.click(screen.getByText('翻译+风格转换'))

    await screen.findByAltText('DDI standard template')

    const submitButton = screen.getByRole('button', { name: /开始翻译/ })
    expect(submitButton).toBeEnabled()

    fireEvent.click(submitButton)

    await waitFor(() => {
      expect(createTranslateProject).toHaveBeenCalledWith(
        expect.anything(),
        expect.objectContaining({
          translateMode: 'restyle',
          styleRefs: [],
          stylePresetId: 'ddi-standard',
          translatePrompt: expect.stringContaining('零重写内容原则'),
        })
      )
    })
  })
})
