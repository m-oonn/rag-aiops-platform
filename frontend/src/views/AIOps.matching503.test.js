import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import ElementPlus from 'element-plus'
import AIOps from './AIOps.vue'
import fixture from './__fixtures__/matching503-api-20261024.json'

describe('actual historical 503 API output in AIOps', () => {
  beforeEach(() => {
    vi.stubGlobal('localStorage', { getItem: vi.fn(key => key === 'token' ? 'test-token' : null), setItem: vi.fn(), removeItem: vi.fn() })
    vi.stubGlobal('location', { href: '/aiops' })
  })
  afterEach(() => {
    vi.unstubAllGlobals()
    vi.restoreAllMocks()
  })

  it.each(fixture.cases)('keeps streamed and restored diagnosis identical: $case / $evidence_count', async row => {
    const tid = row.refreshed.thread_id
    const encoded = new TextEncoder().encode(row.events.map(event => `event: message\r\ndata: ${JSON.stringify(event)}\r\n\r\n`).join(''))
    const fetchSpy = vi.spyOn(global, 'fetch').mockImplementation(async (url, options) => {
      if (url === '/api/v1/aiops' && options?.method === 'POST') {
        return { ok: true, body: new ReadableStream({ start(controller) {
          // Fragment UTF-8 and SSE boundaries like a real streaming transport.
          for (let offset = 0; offset < encoded.length; offset += 127) controller.enqueue(encoded.slice(offset, offset + 127))
          controller.close()
        } }) }
      }
      if (url.endsWith(`/runs/${tid}`)) return { ok: true, json: async () => row.refreshed }
      if (url.endsWith('/evidence')) return { ok: true, json: async () => row.ledger }
      if (url.endsWith('/status')) return { ok: true, json: async () => ({ status: 'offline' }) }
      throw new Error(`unexpected request: ${url}`)
    })
    const checkVisible = wrapper => {
      const banner = wrapper.find('.diagnosis-banner')
      const report = wrapper.find('.report-body')
      expect(banner.text()).toContain('故障层已定位，深层原因未明')
      expect(banner.text()).toContain(row.refreshed.diagnosis.conclusion)
      expect(banner.text()).not.toContain('原因已确认')
      expect(report.text()).toContain('更深原因尚未确认')
      expect(report.text()).not.toContain('下游进程崩溃导致入口503')
      expect(wrapper.text()).toContain('判断校验：自由文本因果解释尚未验证')
      expect(wrapper.text()).toContain('配置依赖 HTTP 健康检查失败')
      expect(wrapper.text()).toContain('人工处理建议')
      expect(wrapper.text()).toContain('以下建议待人工核对，尚未执行；不作为根因证明。')
      expect(wrapper.text()).toContain('建议依据：')
      expect(wrapper.text()).toContain('处理后验证：')
      expect(wrapper.text()).toContain('操作前提：')
      expect(wrapper.text()).toContain('风险：')
      if (row.case === 'downstream_unreachable' && row.evidence_count >= 2) {
        expect(wrapper.text()).toContain('不能说明退出原因')
      } else expect(wrapper.text()).not.toContain('不能说明退出原因')
      if (row.case === 'downstream_unreachable' && row.evidence_count >= 2) {
        expect(banner.text()).toContain('配置依赖 TCP 探测失败')
      } else expect(banner.text()).not.toContain('配置依赖 TCP 探测失败')
      if (row.evidence_count === 3) {
        expect(report.text()).toContain(row.case === 'downstream_unreachable' ? 'upstream connection failed' : 'invalid max_attempts configuration')
      } else expect(report.text()).not.toContain('invalid max_attempts configuration')
      return { banner: banner.text(), report: report.text() }
    }
    let wrapper = mount(AIOps, { global: { plugins: [ElementPlus] } })
    try {
      await wrapper.find('textarea').setValue('本地应用入口返回503，请排查')
      await wrapper.findAll('button').find(b => b.text().includes('开始诊断')).trigger('click')
      await flushPromises()
      const streamed = checkVisible(wrapper)
      expect(localStorage.setItem).toHaveBeenCalledWith('aiops_last_thread', tid)
      wrapper.unmount()
      localStorage.getItem.mockImplementation(key => ({ token: 'test-token', aiops_last_thread: tid })[key] || null)
      wrapper = mount(AIOps, { global: { plugins: [ElementPlus] } })
      await flushPromises()
      expect(checkVisible(wrapper)).toEqual(streamed)
      const adviceRef = wrapper.find('.diagnosis-recommendations button')
      expect(adviceRef.text()).toContain(row.refreshed.diagnosis.recommendations[0].evidence[0].evidence_id)
      await adviceRef.trigger('click')
      await flushPromises()
      expect(wrapper.find('.el-collapse-item__header').attributes('aria-expanded')).toBe('true')
      const firstRef = wrapper.find('.diagnosis-ref')
      expect(firstRef.text()).toBe(row.refreshed.diagnosis.observed_findings[0].evidence_id)
      await firstRef.trigger('click')
      await flushPromises()
      expect(wrapper.find('.el-collapse-item__header').attributes('aria-expanded')).toBe('true')
      expect(fetchSpy.mock.calls.some(([url]) => /\/evidence\/ev-/.test(url))).toBe(false)
    } finally {
      wrapper.unmount()
    }
  })
})
