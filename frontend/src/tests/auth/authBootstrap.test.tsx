import { describe, it, expect, beforeEach, vi } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'

import App from '@/App'
import { getAuthMe } from '@/api/endpoints'

vi.mock('@/pages/Home', () => ({
  Home: () => <div>HOME_PAGE</div>,
}))

vi.mock('@/pages/Landing', () => ({
  Landing: () => <div>LANDING_PAGE</div>,
}))

vi.mock('@/pages/History', () => ({
  History: () => <div>HISTORY_PAGE</div>,
}))

vi.mock('@/pages/OutlineEditor', () => ({
  OutlineEditor: () => <div>OUTLINE_PAGE</div>,
}))

vi.mock('@/pages/DetailEditor', () => ({
  DetailEditor: () => <div>DETAIL_PAGE</div>,
}))

vi.mock('@/pages/SlidePreview', () => ({
  SlidePreview: () => <div>PREVIEW_PAGE</div>,
}))

vi.mock('@/pages/Login', () => ({
  Login: () => <div>LOGIN_PAGE</div>,
}))

vi.mock('@/store/useProjectStore', () => ({
  useProjectStore: () => ({
    currentProject: null,
    syncProject: vi.fn(),
    error: null,
    setError: vi.fn(),
  }),
}))

vi.mock('@/components/shared', () => ({
  useToast: () => ({
    show: vi.fn(),
    ToastContainer: () => null,
  }),
}))

vi.mock('@/api/endpoints', async () => {
  const actual = await vi.importActual<typeof import('@/api/endpoints')>('@/api/endpoints')
  return {
    ...actual,
    getAuthMe: vi.fn(),
  }
})

describe('Auth Bootstrap', () => {
  const storageMock = {
    getItem: vi.fn(() => null),
    setItem: vi.fn(),
    removeItem: vi.fn(),
    clear: vi.fn(),
  }

  beforeEach(() => {
    vi.clearAllMocks()
    Object.defineProperty(window, 'localStorage', {
      value: storageMock,
      writable: true,
    })
  })

  it('redirects to /login when unauthenticated', async () => {
    vi.mocked(getAuthMe).mockRejectedValue({ response: { status: 401 } })

    window.history.replaceState({}, '', '/')
    render(<App />)

    await waitFor(() => {
      expect(screen.getByText('LOGIN_PAGE')).toBeInTheDocument()
    })
  })

  it('enters app when authenticated', async () => {
    vi.mocked(getAuthMe).mockResolvedValue({
      success: true,
      data: {
        user: {
          id: 'user-1',
          is_active: true,
        },
      },
    })

    window.history.replaceState({}, '', '/')
    render(<App />)

    await waitFor(() => {
      expect(screen.getByText('HOME_PAGE')).toBeInTheDocument()
    })
  })

  it('redirects /settings to / when authenticated', async () => {
    vi.mocked(getAuthMe).mockResolvedValue({
      success: true,
      data: {
        user: {
          id: 'user-1',
          is_active: true,
        },
      },
    })

    window.history.replaceState({}, '', '/settings')
    render(<App />)

    await waitFor(() => {
      expect(screen.getByText('HOME_PAGE')).toBeInTheDocument()
    })
  })
})
