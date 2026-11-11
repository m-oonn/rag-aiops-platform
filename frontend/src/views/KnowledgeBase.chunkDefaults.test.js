import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { flushPromises } from '@vue/test-utils'
import { mountWithPlugins } from '../test-utils'
import KnowledgeBase from './KnowledgeBase.vue'
import api from '../api'

vi.mock('../api', () => ({
  default: {
    get: vi.fn(),
    post: vi.fn(),
    put: vi.fn(),
    delete: vi.fn()
  }
}))

/**
 * 新建知识库时前端默认的分块参数必须与后端一致。
 *
 * 后端 `settings.CHUNK_SIZE=1000` / `CHUNK_OVERLAP=200`。前端表单曾默认 500/50，
 * 于是"什么都不改直接建库"建出来的库与后端默认值不同，同一份文档切出来的片段数
 * 也不一样——这类不一致只在检索效果上显现，很难被发现，所以用测试钉死。
 */
describe('KnowledgeBase 分块默认值与后端一致', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  afterEach(() => {
    vi.restoreAllMocks()
  })

  it('新建知识库提交 1000 / 200，而不是前端自己的 500 / 50', async () => {
    api.get.mockResolvedValue({ data: [] })
    api.post.mockResolvedValue({ data: { id: 2, name: 'New KB' } })

    const wrapper = await mountWithPlugins(KnowledgeBase)
    await flushPromises()

    const createButton = wrapper.findAll('button').find((b) => b.text() === '创建知识库')
    await createButton.trigger('click')
    await flushPromises()

    const inputs = wrapper.findAll('input')
    await inputs[0].setValue('New KB')

    const confirmButton = wrapper.findAll('button').find((b) => b.text() === '确定')
    await confirmButton.trigger('click')
    await flushPromises()

    const payload = api.post.mock.calls[0][1]
    expect(payload.chunking_config.chunk_size).toBe(1000)
    expect(payload.chunking_config.chunk_overlap).toBe(200)
  })
})