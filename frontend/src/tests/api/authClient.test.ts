import { describe, it, expect, beforeEach, vi } from 'vitest'

import { apiClient } from '@/api/client'
import { getGlobalTaskStatus } from '@/api/endpoints'

vi.mock('@/api/client', async () => {
  const actual = await vi.importActual<typeof import('@/api/client')>('@/api/client')
  return {
    ...actual,
    apiClient: {
      ...actual.apiClient,
      get: vi.fn(),
    },
  }
})

describe('Auth Client', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('uses owner-scoped global task endpoint', async () => {
    vi.mocked(apiClient.get).mockResolvedValue({
      data: {
        success: true,
        data: {
          task_id: 'task-1',
          status: 'PENDING',
        },
      },
    })

    await getGlobalTaskStatus('task-1')

    expect(apiClient.get).toHaveBeenCalledWith('/api/tasks/task-1')
  })
})
