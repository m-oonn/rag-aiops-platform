import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { flushPromises } from '@vue/test-utils'
import { ElMessageBox } from 'element-plus'
import { mountWithPlugins } from '../test-utils'
import Assistant from './Assistant.vue'
import api from '../api'

vi.mock('../api', () => ({
  default: {
    get: vi.fn(),
    post: vi.fn(),
    put: vi.fn(),
    delete: vi.fn()
  }
}))

describe('Assistant.vue', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    // 删除确认走统一的 confirmAction -> ElMessageBox.confirm
    vi.spyOn(ElMessageBox, 'confirm').mockResolvedValue()
  })

  afterEach(() => {
    vi.restoreAllMocks()
  })

  it('fetches assistants, KBs and agents on mount', async () => {
    api.get.mockImplementation((url) => {
      if (url === '/assistants/') return Promise.resolve({ data: [] })
      if (url === '/knowledge-bases/') return Promise.resolve({ data: [] })
      if (url === '/agents/') return Promise.resolve({ data: [] })
      return Promise.resolve({ data: [] })
    })

    await mountWithPlugins(Assistant)
    await flushPromises()

    expect(api.get).toHaveBeenCalledWith('/assistants/')
    expect(api.get).toHaveBeenCalledWith('/knowledge-bases/')
    expect(api.get).toHaveBeenCalledWith('/agents/')
  })

  it('creates a new assistant', async () => {
    api.get.mockResolvedValue({ data: [] })
    api.post.mockResolvedValue({ data: { id: 1 } })

    const wrapper = await mountWithPlugins(Assistant)
    await flushPromises()

    const createButton = wrapper.findAll('button').find((b) => b.text() === '创建助手')
    await createButton.trigger('click')
    await flushPromises()

    const inputs = wrapper.findAll('input')
    await inputs[0].setValue('Test Assistant')
    await inputs[1].setValue('A helpful assistant')

    const confirmButton = wrapper.findAll('button').find((b) => b.text() === '确定')
    await confirmButton.trigger('click')
    await flushPromises()

    expect(api.post).toHaveBeenCalledWith('/assistants/', expect.objectContaining({
      name: 'Test Assistant',
      description: 'A helpful assistant'
    }))
  })

  it('edits an existing assistant', async () => {
    api.get.mockImplementation((url) => {
      if (url === '/assistants/') {
        return Promise.resolve({
          data: [
            {
              id: 1,
              name: 'Assistant One',
              description: 'Desc',
              llm_model: 'qwen-max',
              temperature: 0.7,
              system_prompt: '',
              greeting_message: '',
              kb_ids: [],
              agent_ids: []
            }
          ]
        })
      }
      return Promise.resolve({ data: [] })
    })
    api.put.mockResolvedValue({ data: {} })

    const wrapper = await mountWithPlugins(Assistant)
    await flushPromises()

    const editButton = wrapper.findAll('button').find((b) => b.text() === '编辑')
    await editButton.trigger('click')
    await flushPromises()

    const inputs = wrapper.findAll('input')
    await inputs[0].setValue('Assistant One Updated')

    const confirmButton = wrapper.findAll('button').find((b) => b.text() === '确定')
    await confirmButton.trigger('click')
    await flushPromises()

    expect(api.put).toHaveBeenCalledWith('/assistants/1', expect.objectContaining({
      name: 'Assistant One Updated'
    }))
  })

  it('deletes an assistant after confirmation', async () => {
    api.get.mockImplementation((url) => {
      if (url === '/assistants/') {
        return Promise.resolve({
          data: [
            { id: 1, name: 'Assistant One', description: 'Desc', llm_model: 'qwen-max' }
          ]
        })
      }
      return Promise.resolve({ data: [] })
    })
    api.delete.mockResolvedValue({ data: {} })

    const wrapper = await mountWithPlugins(Assistant)
    await flushPromises()

    const deleteButton = wrapper.findAll('button').find((b) => b.text() === '删除')
    await deleteButton.trigger('click')
    await flushPromises()

    expect(ElMessageBox.confirm).toHaveBeenCalled()
    expect(api.delete).toHaveBeenCalledWith('/assistants/1')
  })

  it('starts chat and loads latest session', async () => {
    api.get.mockImplementation((url) => {
      if (url === '/assistants/') {
        return Promise.resolve({
          data: [
            { id: 1, name: 'Assistant One', description: 'Desc', llm_model: 'qwen-max', kb_ids: [] }
          ]
        })
      }
      if (url === '/knowledge-bases/') return Promise.resolve({ data: [] })
      if (url === '/agents/') return Promise.resolve({ data: [] })
      if (url === '/chat/sessions') {
        return Promise.resolve({
          data: [
            { session_uid: 'sess-1', assistant_id: 1, created_at: '2024-01-02T00:00:00Z' },
            { session_uid: 'sess-2', assistant_id: 1, created_at: '2024-01-01T00:00:00Z' }
          ]
        })
      }
      if (url === '/chat/sessions/sess-1/messages') {
        return Promise.resolve({
          data: [{ query: 'Hi', answer: 'Hello', source_documents: [] }]
        })
      }
      if (url === '/assistants/1/versions') return Promise.resolve({ data: [] })
      return Promise.resolve({ data: [] })
    })

    const wrapper = await mountWithPlugins(Assistant)
    await flushPromises()

    const chatButton = wrapper.findAll('button').find((b) => b.text() === '会话')
    await chatButton.trigger('click')
    await flushPromises()

    expect(api.get).toHaveBeenCalledWith('/chat/sessions')
    expect(api.get).toHaveBeenCalledWith('/chat/sessions/sess-1/messages')
    expect(wrapper.vm.currentSessionId).toBe('sess-1')
    expect(wrapper.vm.chatVisible).toBe(true)
  })
})
