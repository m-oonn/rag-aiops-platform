import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { flushPromises } from '@vue/test-utils'
import { mountWithPlugins } from '../test-utils'
import KnowledgeBase from './KnowledgeBase.vue'
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

describe('KnowledgeBase.vue', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    vi.spyOn(ElMessageBox, 'confirm').mockResolvedValue()
  })

  afterEach(() => {
    vi.restoreAllMocks()
  })

  it('fetches and displays knowledge bases on mount', async () => {
    api.get.mockResolvedValue({
      data: [
        { id: 1, name: 'KB One', description: 'First KB', created_at: '2024-01-01T00:00:00Z' }
      ]
    })

    const wrapper = await mountWithPlugins(KnowledgeBase)
    await flushPromises()

    expect(api.get).toHaveBeenCalledWith('/knowledge-bases/')
    expect(wrapper.text()).toContain('KB One')
    expect(wrapper.text()).toContain('First KB')
  })

  it('creates a new knowledge base', async () => {
    api.get.mockResolvedValue({ data: [] })
    api.post.mockResolvedValue({ data: { id: 2, name: 'New KB' } })

    const wrapper = await mountWithPlugins(KnowledgeBase)
    await flushPromises()

    const createButton = wrapper.findAll('button').find((b) => b.text() === '创建知识库')
    await createButton.trigger('click')
    await flushPromises()

    const inputs = wrapper.findAll('input')
    await inputs[0].setValue('New KB')
    await inputs[1].setValue('A test KB')

    const confirmButton = wrapper.findAll('button').find((b) => b.text() === '确定')
    await confirmButton.trigger('click')
    await flushPromises()

    expect(api.post).toHaveBeenCalledWith('/knowledge-bases/', expect.objectContaining({
      name: 'New KB',
      description: 'A test KB'
    }))
  })

  it('deletes a knowledge base', async () => {
    api.get.mockResolvedValue({
      data: [
        { id: 1, name: 'KB One', description: 'First KB', created_at: '2024-01-01T00:00:00Z' }
      ]
    })
    api.delete.mockResolvedValue({ data: {} })

    const wrapper = await mountWithPlugins(KnowledgeBase)
    await flushPromises()

    // Find delete button by icon class
    const deleteButton = wrapper.findAll('button').find((b) => b.classes().includes('el-button--danger'))
    expect(deleteButton).toBeDefined()
    await deleteButton.trigger('click')
    await flushPromises()

    expect(api.delete).toHaveBeenCalledWith('/knowledge-bases/1')
  })

  it('navigates to detail when card is clicked', async () => {
    api.get.mockResolvedValue({
      data: [
        { id: 1, name: 'KB One', description: 'First KB', created_at: '2024-01-01T00:00:00Z' }
      ]
    })

    const wrapper = await mountWithPlugins(KnowledgeBase, {
      routes: [
        { path: '/', component: KnowledgeBase },
        { path: '/knowledge-bases/:id', component: { template: '<div>Detail</div>' } }
      ]
    })
    await flushPromises()

    const card = wrapper.find('.kb-card')
    await card.trigger('click')
    await flushPromises()

    expect(wrapper.vm.$route.path).toBe('/knowledge-bases/1')
  })

  it('edits a knowledge base', async () => {
    api.get.mockResolvedValue({
      data: [
        { id: 1, name: 'KB One', description: 'First KB', created_at: '2024-01-01T00:00:00Z' }
      ]
    })
    api.put.mockResolvedValue({ data: {} })

    const wrapper = await mountWithPlugins(KnowledgeBase)
    await flushPromises()

    const editButton = wrapper.findAll('button').find((b) =>
      b.classes().includes('el-button--primary') &&
      b.classes().includes('is-circle') &&
      !b.classes().includes('el-button--danger')
    )
    expect(editButton).toBeDefined()
    await editButton.trigger('click')
    await flushPromises()

    const inputs = wrapper.findAll('input')
    await inputs[0].setValue('KB One Updated')

    const saveButton = wrapper.findAll('button').find((b) => b.text() === '保存')
    await saveButton.trigger('click')
    await flushPromises()

    expect(api.put).toHaveBeenCalledWith('/knowledge-bases/1', expect.objectContaining({
      name: 'KB One Updated'
    }))
  })
})
