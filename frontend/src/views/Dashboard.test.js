import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { flushPromises } from '@vue/test-utils'
import { mountWithPlugins } from '../test-utils'
import Dashboard from './Dashboard.vue'
import api from '../api'

vi.mock('../api', () => ({
  default: {
    get: vi.fn(),
    post: vi.fn(),
    put: vi.fn(),
    delete: vi.fn()
  }
}))

describe('Dashboard.vue', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    api.get.mockImplementation((url) => {
      if (url === '/knowledge-bases/') {
        return Promise.resolve({ data: [{ id: 1, name: '运维知识库' }] })
      }
      if (url === '/knowledge-bases/1/documents') {
        return Promise.resolve({ data: [{ id: 11 }, { id: 12 }] })
      }
      if (url === '/monitor/stats') {
        return Promise.resolve({ data: { total_pending: 3, total_processing: 1, total_failed: 0, total_completed: 9 } })
      }
      if (url === '/evaluations/tasks') {
        return Promise.resolve({ data: [{ id: 1 }, { id: 2 }] })
      }
      if (url === '/health/dependencies') {
        return Promise.resolve({
          data: {
            overall: 'degraded',
            services: {
              mcp_monitor: { status: 'ok' },
              mcp_cls: { status: 'ok' },
              rabbitmq: { status: 'unavailable' },
              redis: { status: 'ok' },
              milvus: { status: 'unavailable' },
              minio: { status: 'unavailable' },
              llm: { status: 'ok' }
            }
          }
        })
      }
      return Promise.resolve({ data: [] })
    })
  })

  afterEach(() => {
    vi.restoreAllMocks()
  })

  it('渲染中文工作台内容并加载真实统计', async () => {
    const wrapper = await mountWithPlugins(Dashboard)
    await flushPromises()
    const text = wrapper.text()
    expect(text).toContain('工作台')
    expect(text).toContain('服务状态')
    expect(text).toContain('快捷入口')
    expect(text).toContain('故障诊断')
    expect(text).toContain('知识问答')
    expect(text).not.toContain('Dashboard')
    expect(text).not.toContain('Welcome to the AIOps Agent Platform')
    expect(text).not.toContain('Manage Knowledge Bases')
    expect(text).not.toContain('Start Chat')
    expect(text).not.toContain('Run Evaluation')
  })

  it('统计卡片展示接口返回的数据', async () => {
    const wrapper = await mountWithPlugins(Dashboard)
    await flushPromises()
    const text = wrapper.text()
    expect(text).toContain('知识库')
    expect(text).toContain('1') // 1 个知识库
    expect(text).toContain('2') // 2 份文档
    expect(text).toContain('4') // 待处理 3 + 处理中 1
    expect(text).toContain('评测任务')
  })

  it('服务状态区显示各依赖的可用性', async () => {
    const wrapper = await mountWithPlugins(Dashboard)
    await flushPromises()
    const text = wrapper.text()
    expect(text).toContain('监控指标服务')
    expect(text).toContain('日志检索服务')
    expect(text).toContain('向量库')
    expect(text).toContain('降级')
  })
})
