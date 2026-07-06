import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { flushPromises } from '@vue/test-utils'
import { mountWithPlugins } from '../test-utils'
import Monitor from './Monitor.vue'
import api from '../api'
import { ElMessageBox } from 'element-plus'

vi.mock('../api', () => ({
  default: {
    get: vi.fn(),
    post: vi.fn(),
    put: vi.fn(),
    delete: vi.fn()
  }
}))

describe('Monitor.vue', () => {
  let storage = {}

  beforeEach(() => {
    storage = {}
    vi.clearAllMocks()
    vi.spyOn(ElMessageBox, 'confirm').mockResolvedValue()
    vi.spyOn(global.Storage.prototype, 'getItem').mockImplementation((key) => storage[key] || null)
    vi.spyOn(global.Storage.prototype, 'setItem').mockImplementation((key, value) => {
      storage[key] = value
    })
    vi.spyOn(global.Storage.prototype, 'removeItem').mockImplementation((key) => {
      delete storage[key]
    })
  })

  afterEach(() => {
    vi.restoreAllMocks()
  })

  it('fetches stats and queue on mount', async () => {
    api.get.mockImplementation((url) => {
      if (url === '/monitor/stats') return Promise.resolve({ data: { total_pending: 1, total_processing: 2, total_failed: 3, total_completed: 4 } })
      if (url === '/monitor/') return Promise.resolve({ data: [] })
      return Promise.resolve({ data: [] })
    })

    const wrapper = await mountWithPlugins(Monitor)
    await flushPromises()

    expect(api.get).toHaveBeenCalledWith('/monitor/stats')
    expect(api.get).toHaveBeenCalledWith('/monitor/', { params: { status_filter: undefined } })
    expect(wrapper.text()).toContain('1')
    expect(wrapper.text()).toContain('2')
    expect(wrapper.text()).toContain('3')
    expect(wrapper.text()).toContain('4')
  })

  it('clears the polling interval when unmounted', async () => {
    api.get.mockResolvedValue({ data: [] })
    const setIntervalSpy = vi.spyOn(global, 'setInterval')
    const clearIntervalSpy = vi.spyOn(global, 'clearInterval')

    const wrapper = await mountWithPlugins(Monitor)
    await flushPromises()

    const pollCalls = setIntervalSpy.mock.calls.filter((call) => call[1] === 3000)
    expect(pollCalls.length).toBeGreaterThanOrEqual(1)
    const intervalId = setIntervalSpy.mock.results[
      setIntervalSpy.mock.calls.findIndex((call) => call[1] === 3000)
    ].value

    wrapper.unmount()
    await flushPromises()

    expect(clearIntervalSpy).toHaveBeenCalledWith(intervalId)
  })

  it('deletes a queue item after confirmation', async () => {
    api.get.mockImplementation((url) => {
      if (url === '/monitor/stats') return Promise.resolve({ data: { total_pending: 0, total_processing: 0, total_failed: 1, total_completed: 0 } })
      if (url === '/monitor/') {
        return Promise.resolve({
          data: [
            { task_id: 'task-1', filename: 'doc.pdf', kb_name: 'KB', status: 'FAILURE', progress: 0, message: 'Failed', created_at: '2024-01-01T00:00:00Z' }
          ]
        })
      }
      return Promise.resolve({ data: [] })
    })
    api.delete.mockResolvedValue({ data: {} })

    const wrapper = await mountWithPlugins(Monitor)
    await flushPromises()

    const deleteButton = wrapper.findAll('button').find((b) => b.text() === '删除')
    expect(deleteButton).toBeDefined()
    await deleteButton.trigger('click')
    await flushPromises()

    expect(api.delete).toHaveBeenCalledWith('/monitor/tasks/task-1')
  })

  it('filters queue by status', async () => {
    api.get.mockImplementation((url, config) => {
      if (url === '/monitor/stats') return Promise.resolve({ data: { total_pending: 0, total_processing: 0, total_failed: 0, total_completed: 0 } })
      if (url === '/monitor/') {
        const status = config?.params?.status_filter
        return Promise.resolve({
          data: status === 'pending'
            ? [{ task_id: 'task-1', filename: 'pending.pdf', status: 'PENDING', progress: 0, message: '', created_at: '2024-01-01T00:00:00Z' }]
            : []
        })
      }
      return Promise.resolve({ data: [] })
    })

    const wrapper = await mountWithPlugins(Monitor)
    await flushPromises()

    // Simulate filter change directly
    wrapper.vm.filterStatus = 'pending'
    await wrapper.vm.fetchQueue()
    await flushPromises()

    expect(api.get).toHaveBeenCalledWith('/monitor/', { params: { status_filter: 'pending' } })
  })

  it('logs in to MinIO and fetches files', async () => {
    api.get.mockResolvedValue({ data: [] })
    api.post.mockResolvedValue({ data: {} })

    const wrapper = await mountWithPlugins(Monitor)
    await flushPromises()

    // Switch to MinIO tab
    wrapper.vm.activeTab = 'minio'
    await flushPromises()

    // Fill login form
    wrapper.vm.minioForm.accessKey = 'minioadmin'
    wrapper.vm.minioForm.secretKey = 'minioadmin'
    await flushPromises()

    wrapper.vm.handleMinioLogin()
    await flushPromises()

    expect(storage.minio_auth_status).toBe('connected')
    expect(wrapper.vm.minioConnected).toBe(true)
  })
})
