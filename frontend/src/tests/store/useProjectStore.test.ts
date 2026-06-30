/**
 * Zustand Store 测试
 * 
 * 测试useProjectStore的核心状态管理功能
 */

import { describe, it, expect, beforeEach, vi } from 'vitest'
import { act, renderHook } from '@testing-library/react'
import { useProjectStore } from '@/store/useProjectStore'

// Mock API模块
vi.mock('@/api/endpoints', () => ({
  createProject: vi.fn(),
  getProject: vi.fn(),
  updatePage: vi.fn(),
  updatePageDescription: vi.fn(),
  updatePageOutline: vi.fn(),
  generateOutline: vi.fn(),
  generateDescriptions: vi.fn(),
  generateImages: vi.fn(),
  translateGenerate: vi.fn(),
  translateSinglePage: vi.fn(),
  getTaskStatus: vi.fn(),
  exportPPTX: vi.fn(),
  exportPDF: vi.fn(),
}))

const api = await import('@/api/endpoints')

describe('useProjectStore', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    // 重置store状态
    const { result } = renderHook(() => useProjectStore())
    act(() => {
      result.current.setCurrentProject(null)
      result.current.setError(null)
      result.current.setGlobalLoading(false)
      useProjectStore.setState({
        pageGeneratingTasks: {},
        pageDescriptionGeneratingTasks: {},
        warningMessage: null,
      })
    })
  })

  describe('初始状态', () => {
    it('should initialize with default state', () => {
      const { result } = renderHook(() => useProjectStore())
      
      expect(result.current.currentProject).toBeNull()
      expect(result.current.isGlobalLoading).toBe(false)
      expect(result.current.error).toBeNull()
      expect(result.current.activeTaskId).toBeNull()
    })
  })

  describe('基础Setters', () => {
    it('should set current project correctly', () => {
      const { result } = renderHook(() => useProjectStore())
      const mockProject = { 
        id: '123', 
        status: 'DRAFT',
        pages: [],
        created_at: new Date().toISOString()
      }
      
      act(() => {
        result.current.setCurrentProject(mockProject as any)
      })
      
      expect(result.current.currentProject).toEqual(mockProject)
    })

    it('should set global loading state', () => {
      const { result } = renderHook(() => useProjectStore())
      
      act(() => {
        result.current.setGlobalLoading(true)
      })
      
      expect(result.current.isGlobalLoading).toBe(true)
      
      act(() => {
        result.current.setGlobalLoading(false)
      })
      
      expect(result.current.isGlobalLoading).toBe(false)
    })

    it('should set error correctly', () => {
      const { result } = renderHook(() => useProjectStore())
      
      act(() => {
        result.current.setError('Test error')
      })
      
      expect(result.current.error).toBe('Test error')
      
      act(() => {
        result.current.setError(null)
      })
      
      expect(result.current.error).toBeNull()
    })
  })

  describe('本地页面更新', () => {
    it('should update page locally (optimistic update)', () => {
      const { result } = renderHook(() => useProjectStore())
      
      // 先设置项目
      const mockProject = {
        id: 'proj-123',
        status: 'DRAFT',
        pages: [
          { id: 'page-1', outline_content: { title: 'Page 1', points: [] } },
          { id: 'page-2', outline_content: { title: 'Page 2', points: [] } },
        ]
      }
      
      act(() => {
        result.current.setCurrentProject(mockProject as any)
      })
      
      // 更新页面
      act(() => {
        result.current.updatePageLocal('page-1', { 
          outline_content: { title: 'Updated Page 1', points: ['new point'] }
        })
      })
      
      // 验证乐观更新
      const updatedPage = result.current.currentProject?.pages.find(p => p.id === 'page-1')
      expect(updatedPage?.outline_content?.title).toBe('Updated Page 1')
    })
  })

  describe('清除状态', () => {
    it('should clear project by setting null', () => {
      const { result } = renderHook(() => useProjectStore())
      
      // 先设置项目
      act(() => {
        result.current.setCurrentProject({ id: '123', pages: [] } as any)
      })
      
      expect(result.current.currentProject).not.toBeNull()
      
      // 清除
      act(() => {
        result.current.setCurrentProject(null)
      })
      
      expect(result.current.currentProject).toBeNull()
    })
  })

  describe('图片生成', () => {
    it('should route translate projects to translate batch generation API', async () => {
      vi.mocked(api.translateGenerate).mockResolvedValue({
        data: { task_id: 'task-translate', status: 'PENDING', total_pages: 2, translate_mode: 'pure', target_language: 'English' },
      } as any)
      vi.mocked(api.getTaskStatus).mockResolvedValue({
        data: { task_id: 'task-translate', status: 'PROCESSING', progress: { total: 2, completed: 0 } },
      } as any)
      vi.mocked(api.getProject).mockResolvedValue({
        data: {
          project_id: 'proj-translate',
          id: 'proj-translate',
          creation_type: 'translate',
          pages: [
            { page_id: 'page-1', id: 'page-1', order_index: 0, outline_content: { title: 'A', points: [] }, status: 'DRAFT' },
            { page_id: 'page-2', id: 'page-2', order_index: 1, outline_content: { title: 'B', points: [] }, status: 'DRAFT' },
          ],
          status: 'SLIDES_EXTRACTED',
          created_at: '',
          updated_at: '',
        },
      } as any)

      const { result } = renderHook(() => useProjectStore())
      act(() => {
        result.current.setCurrentProject({
          project_id: 'proj-translate',
          id: 'proj-translate',
          idea_prompt: '',
          creation_type: 'translate',
          pages: [
            { page_id: 'page-1', id: 'page-1', order_index: 0, outline_content: { title: 'A', points: [] }, status: 'DRAFT' },
            { page_id: 'page-2', id: 'page-2', order_index: 1, outline_content: { title: 'B', points: [] }, status: 'DRAFT' },
          ],
          status: 'SLIDES_EXTRACTED',
          created_at: '',
          updated_at: '',
        } as any)
      })

      await act(async () => {
        await result.current.generateImages()
      })

      expect(api.translateGenerate).toHaveBeenCalledWith('proj-translate', undefined)
      expect(api.generateImages).not.toHaveBeenCalled()
      expect(result.current.pageGeneratingTasks).toEqual({
        'page-1': 'task-translate',
        'page-2': 'task-translate',
      })
    })

    it('should route translate single page generation to translate API', async () => {
      vi.mocked(api.translateSinglePage).mockResolvedValue({
        data: { task_id: 'task-single', status: 'PENDING', translate_mode: 'pure', target_language: 'English' },
      } as any)
      vi.mocked(api.getTaskStatus).mockResolvedValue({
        data: { task_id: 'task-single', status: 'PROCESSING', progress: { total: 1, completed: 0 } },
      } as any)
      vi.mocked(api.getProject).mockResolvedValue({
        data: {
          project_id: 'proj-translate',
          id: 'proj-translate',
          creation_type: 'translate',
          pages: [
            { page_id: 'page-1', id: 'page-1', order_index: 0, outline_content: { title: 'A', points: [] }, status: 'DRAFT' },
            { page_id: 'page-2', id: 'page-2', order_index: 1, outline_content: { title: 'B', points: [] }, status: 'DRAFT' },
          ],
          status: 'SLIDES_EXTRACTED',
          created_at: '',
          updated_at: '',
        },
      } as any)

      const { result } = renderHook(() => useProjectStore())
      act(() => {
        result.current.setCurrentProject({
          project_id: 'proj-translate',
          id: 'proj-translate',
          idea_prompt: '',
          creation_type: 'translate',
          pages: [
            { page_id: 'page-1', id: 'page-1', order_index: 0, outline_content: { title: 'A', points: [] }, status: 'DRAFT' },
            { page_id: 'page-2', id: 'page-2', order_index: 1, outline_content: { title: 'B', points: [] }, status: 'DRAFT' },
          ],
          status: 'SLIDES_EXTRACTED',
          created_at: '',
          updated_at: '',
        } as any)
      })

      await act(async () => {
        await result.current.generateImages(['page-2'])
      })

      expect(api.translateSinglePage).toHaveBeenCalledWith('proj-translate', 'page-2')
      expect(api.translateGenerate).not.toHaveBeenCalled()
      expect(api.generateImages).not.toHaveBeenCalled()
      expect(result.current.pageGeneratingTasks).toEqual({ 'page-2': 'task-single' })
    })
  })
})
