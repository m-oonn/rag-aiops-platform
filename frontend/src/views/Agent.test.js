import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { flushPromises } from '@vue/test-utils'
import { mountWithPlugins } from '../test-utils'
import Agent from './Agent.vue'
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

describe('Agent.vue', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    vi.spyOn(ElMessageBox, 'confirm').mockResolvedValue()
  })

  afterEach(() => {
    vi.restoreAllMocks()
  })

  it('fetches agents on mount', async () => {
    api.get.mockResolvedValue({ data: [] })

    await mountWithPlugins(Agent)
    await flushPromises()

    expect(api.get).toHaveBeenCalledWith('/agents/')
  })

  it('creates a new agent', async () => {
    api.get.mockResolvedValue({ data: [] })
    api.post.mockResolvedValue({ data: { id: 1 } })

    const wrapper = await mountWithPlugins(Agent)
    await flushPromises()

    const createButton = wrapper.findAll('button').find((b) => b.text() === '创建智能体')
    await createButton.trigger('click')
    await flushPromises()

    const inputs = wrapper.findAll('input')
    await inputs[0].setValue('Data Agent')

    const saveButton = wrapper.findAll('button').find((b) => b.text() === '保存')
    await saveButton.trigger('click')
    await flushPromises()

    expect(api.post).toHaveBeenCalledWith('/agents/', expect.objectContaining({
      name: 'Data Agent'
    }))
  })

  it('edits an existing agent', async () => {
    api.get.mockImplementation((url) => {
      if (url === '/agents/') {
        return Promise.resolve({
          data: [
            {
              id: 1,
              name: 'Agent One',
              description: 'Desc',
              type: 'function_call',
              system_prompt: '',
              tools_config: { tools: [], permissions: [] },
              knowledge_config: { kb_ids: [], recall_strategy: 'hybrid', top_k: 5 },
              memory_config: { enable_short_term: true, window_size: 10, enable_long_term: false },
              reasoning_config: { max_steps: 10, allow_parallel: true },
              security_config: { safety_level: 'moderate', allowed_actions: [], allow_internet: false },
              interaction_config: { output_format: 'markdown', response_style: 'professional', clarify_enabled: true },
              llm_config: { model_name: 'qwen-max', temperature: 0.7, max_tokens: 2048 },
              execution_config: { timeout: 60, retry_times: 3, fallback_response: '' }
            }
          ]
        })
      }
      if (url === '/knowledge-bases/') return Promise.resolve({ data: [] })
      return Promise.resolve({ data: [] })
    })
    api.put.mockResolvedValue({ data: {} })

    const wrapper = await mountWithPlugins(Agent)
    await flushPromises()

    const editButton = wrapper.findAll('button').find((b) => b.text() === '编辑')
    await editButton.trigger('click')
    await flushPromises()

    const inputs = wrapper.findAll('input')
    await inputs[0].setValue('Agent One Updated')

    const saveButton = wrapper.findAll('button').find((b) => b.text() === '保存')
    await saveButton.trigger('click')
    await flushPromises()

    expect(api.put).toHaveBeenCalledWith('/agents/1', expect.objectContaining({
      name: 'Agent One Updated'
    }))
  })

  it('deletes an agent after confirmation', async () => {
    api.get.mockImplementation((url) => {
      if (url === '/agents/') {
        return Promise.resolve({
          data: [
            { id: 1, name: 'Agent One', description: 'Desc', type: 'function_call' }
          ]
        })
      }
      return Promise.resolve({ data: [] })
    })
    api.delete.mockResolvedValue({ data: {} })

    const wrapper = await mountWithPlugins(Agent)
    await flushPromises()

    const deleteButton = wrapper.findAll('button').find((b) => b.text() === '删除')
    await deleteButton.trigger('click')
    await flushPromises()

    expect(api.delete).toHaveBeenCalledWith('/agents/1')
  })

  it('formats agent type for display', async () => {
    api.get.mockImplementation((url) => {
      if (url === '/agents/') {
        return Promise.resolve({
          data: [
            { id: 1, name: 'Agent One', type: 'react' }
          ]
        })
      }
      return Promise.resolve({ data: [] })
    })

    const wrapper = await mountWithPlugins(Agent)
    await flushPromises()

    expect(wrapper.text()).toContain('ReAct')
  })
})
