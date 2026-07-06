import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { flushPromises } from '@vue/test-utils'
import { mountWithPlugins } from '../test-utils'
import KnowledgeBaseDetail from './KnowledgeBaseDetail.vue'
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

async function mountDetail() {
  return mountWithPlugins(KnowledgeBaseDetail, {
    route: '/knowledge-bases/1',
    routes: [
      { path: '/knowledge-bases', component: { template: '<div>List</div>' } },
      { path: '/knowledge-bases/:id', component: KnowledgeBaseDetail }
    ]
  })
}

describe('KnowledgeBaseDetail.vue', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    vi.spyOn(ElMessageBox, 'confirm').mockResolvedValue()
    vi.spyOn(ElMessageBox, 'prompt').mockResolvedValue({ value: '5' })
  })

  afterEach(() => {
    vi.restoreAllMocks()
  })

  it('fetches KB details and documents on mount', async () => {
    api.get.mockImplementation((url) => {
      if (url === '/knowledge-bases/1') return Promise.resolve({ data: { id: 1, name: 'KB One' } })
      if (url === '/knowledge-bases/1/documents') return Promise.resolve({ data: [] })
      return Promise.resolve({ data: [] })
    })

    const wrapper = await mountDetail()
    await flushPromises()

    expect(api.get).toHaveBeenCalledWith('/knowledge-bases/1')
    expect(api.get).toHaveBeenCalledWith('/knowledge-bases/1/documents')
    expect(wrapper.text()).toContain('KB One')
  })

  it('clears the polling interval when unmounted', async () => {
    api.get.mockResolvedValue({ data: [] })
    const setIntervalSpy = vi.spyOn(global, 'setInterval')
    const clearIntervalSpy = vi.spyOn(global, 'clearInterval')

    const wrapper = await mountDetail()
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

  it('deletes selected documents in batch', async () => {
    api.get.mockImplementation((url) => {
      if (url === '/knowledge-bases/1') return Promise.resolve({ data: { id: 1, name: 'KB One' } })
      if (url === '/knowledge-bases/1/documents') {
        return Promise.resolve({
          data: [
            { id: 10, filename: 'doc1.pdf', status: 2, chunk_count: 5, created_at: '2024-01-01T00:00:00Z' }
          ]
        })
      }
      return Promise.resolve({ data: [] })
    })
    api.delete.mockResolvedValue({ data: {} })

    const wrapper = await mountDetail()
    await flushPromises()

    // Simulate selection change directly
    wrapper.vm.selectedDocs = [{ id: 10 }]
    await flushPromises()

    const batchDeleteButton = wrapper.findAll('button').find((b) => b.text().includes('批量删除'))
    expect(batchDeleteButton).toBeDefined()
    await batchDeleteButton.trigger('click')
    await flushPromises()

    expect(api.delete).toHaveBeenCalledWith('/knowledge-bases/documents/batch-delete', { data: [10] })
  })

  it('retries a failed document', async () => {
    api.get.mockImplementation((url) => {
      if (url === '/knowledge-bases/1') return Promise.resolve({ data: { id: 1, name: 'KB One' } })
      if (url === '/knowledge-bases/1/documents') {
        return Promise.resolve({
          data: [
            { id: 10, filename: 'doc1.pdf', status: 3, chunk_count: 0, created_at: '2024-01-01T00:00:00Z' }
          ]
        })
      }
      return Promise.resolve({ data: [] })
    })
    api.post.mockResolvedValue({ data: {} })

    const wrapper = await mountDetail()
    await flushPromises()

    const retryButton = wrapper.findAll('button').find((b) => b.text() === '重试')
    expect(retryButton).toBeDefined()
    await retryButton.trigger('click')
    await flushPromises()

    expect(api.post).toHaveBeenCalledWith('/knowledge-bases/documents/10/retry')
  })

  it('views QA pairs for a document', async () => {
    api.get.mockImplementation((url) => {
      if (url === '/knowledge-bases/1') return Promise.resolve({ data: { id: 1, name: 'KB One' } })
      if (url === '/knowledge-bases/1/documents') {
        return Promise.resolve({
          data: [
            { id: 10, filename: 'doc1.pdf', status: 2, chunk_count: 5, created_at: '2024-01-01T00:00:00Z' }
          ]
        })
      }
      if (url === '/knowledge-bases/documents/10/qa-pairs') {
        return Promise.resolve({
          data: [
            { id: 100, question: 'Q1', answer: 'A1', qa_type: 'single_hop' }
          ]
        })
      }
      return Promise.resolve({ data: [] })
    })

    const wrapper = await mountDetail()
    await flushPromises()

    const manageQAButton = wrapper.findAll('button').find((b) => b.text() === '管理 QA')
    expect(manageQAButton).toBeDefined()
    await manageQAButton.trigger('click')
    await flushPromises()

    expect(api.get).toHaveBeenCalledWith('/knowledge-bases/documents/10/qa-pairs')
    expect(wrapper.text()).toContain('Q1')
  })

  it('saves a new QA pair', async () => {
    api.get.mockImplementation((url) => {
      if (url === '/knowledge-bases/1') return Promise.resolve({ data: { id: 1, name: 'KB One' } })
      if (url === '/knowledge-bases/1/documents') {
        return Promise.resolve({
          data: [
            { id: 10, filename: 'doc1.pdf', status: 2, chunk_count: 5, created_at: '2024-01-01T00:00:00Z' }
          ]
        })
      }
      if (url === '/knowledge-bases/documents/10/qa-pairs') {
        return Promise.resolve({ data: [] })
      }
      return Promise.resolve({ data: [] })
    })
    api.post.mockResolvedValue({ data: {} })

    const wrapper = await mountDetail()
    await flushPromises()

    wrapper.vm.currentDocId = 10
    wrapper.vm.openQAForm()
    await flushPromises()

    wrapper.vm.qaForm.question = 'New Question'
    wrapper.vm.qaForm.answer = 'New Answer'
    await flushPromises()

    wrapper.vm.saveQA()
    await flushPromises()

    expect(api.post).toHaveBeenCalledWith('/knowledge-bases/documents/10/qa-pairs', expect.objectContaining({
      question: 'New Question',
      answer: 'New Answer'
    }))
  })
})
