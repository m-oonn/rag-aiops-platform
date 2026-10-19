import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import ElementPlus from 'element-plus'
import AIOps from './AIOps.vue'

describe('AIOps.vue', () => {
  it.each([null, { version: 1, kind: 'localized_fault', scope: 'orders entry', target_id: 'windows-local-01',
    conclusion: '入口返回503，原因未明', stop_reason: '缺少下游证据',
    observed_findings: [{ evidence_id: 'ev-123', summary: '依赖 TCP 探测失败', collected_at: '2026-10-18T01:00:00Z' }],
    unresolved_questions: [{ id: 'q-1', question: '下游是否恢复' }], validation_issues: ['因果解释未验证'],
    evidence: [{ evidence_id: 'ev-123', quote: '503' }], alternatives: [{ explanation: '下游网络', status: 'unresolved', limitation: '未登记' }] }])(
    'restores structured diagnosis or labels historical reports: %s', async (diagnosis) => {
      localStorage.getItem.mockImplementation((key) => ({ token: 'test-token', aiops_last_thread: 'diagnosis-run' })[key] || null)
      vi.spyOn(global, 'fetch').mockImplementation(async (url) => {
        if (url.endsWith('/diagnosis-run')) return { ok: true, json: async () => ({ status: 'completed', report: 'report text', diagnosis }) }
        if (url.endsWith('/evidence')) return { ok: true, json: async () => ({ evidence: [] }) }
        throw new Error('unexpected request')
      })
      const wrapper = mount(AIOps, { global: { plugins: [ElementPlus] } })
      await flushPromises()
      if (diagnosis) {
        expect(wrapper.text()).toContain('故障层已定位，深层原因未明')
        expect(wrapper.text()).toContain('orders entry')
        expect(wrapper.text()).toContain('缺少下游证据')
        expect(wrapper.text()).toContain('未决解释')
        expect(wrapper.text()).toContain('已观察到：依赖 TCP 探测失败')
        expect(wrapper.text()).toContain('未决问题：下游是否恢复')
        expect(wrapper.text()).toContain('判断校验：因果解释未验证')
        expect(wrapper.findAll('button').some(b => b.text().includes('ev-123'))).toBe(true)
      } else expect(wrapper.text()).toContain('历史格式')
      wrapper.unmount()
    })
  beforeEach(() => {
    vi.stubGlobal('localStorage', {
      getItem: vi.fn(() => 'test-token'),
      setItem: vi.fn(),
      removeItem: vi.fn(),
    })
    vi.stubGlobal('location', { href: '/aiops' })
  })

  afterEach(() => {
    vi.unstubAllGlobals()
    vi.restoreAllMocks()
  })

  it.each([false, true])('restores real ledger fields and gates raw expansion: auditor=%s', async (auditor) => {
    localStorage.getItem.mockImplementation((key) => ({ token: 'test-token', aiops_last_thread: 'ledger-thread' })[key] || null)
    let fresh = true
    const fetchSpy = vi.spyOn(global, 'fetch').mockImplementation(async (url) => {
      if (url === '/api/v1/aiops/runs/ledger-thread') return { ok: true, json: async () => ({ thread_id: 'ledger-thread', status: 'completed', report: '现场采集验收' }) }
      if (url.endsWith('/evidence/ev-123')) return { ok: true, json: async () => ({ raw: { payload: { state: 'running', password: '[REDACTED]' } } }) }
      if (url.endsWith('/evidence')) return { ok: true, json: async () => ({ can_read_raw: auditor, evidence: [{ evidence_id: 'ev-123', target_id: 'windows-local-01', source: 'windows_probe', kind: 'services', collected_at: '2026-10-17T01:00:00Z', summary: 'EventLog=running', fresh, raw_available: true }] }) }
      if (url.endsWith('/status')) return { ok: true, json: async () => ({ status: 'online', last_seen: '2026-10-17T01:00:00Z' }) }
      throw new Error(`unexpected ${url}`)
    })
    const wrapper = mount(AIOps, { global: { plugins: [ElementPlus] } })
    await flushPromises()
    expect(wrapper.text()).toContain('证据时间线')
    expect(wrapper.text()).toContain('windows-local-01')
    expect(wrapper.text()).toContain('EventLog=running')
    expect(wrapper.text()).toContain('在线')
    expect(wrapper.text()).toContain('2026-10-17T01:00:00Z')
    const rawButton = wrapper.findAll('button').find((b) => b.text().includes('查看现场证据'))
    expect(Boolean(rawButton)).toBe(auditor)
    if (auditor) {
      await rawButton.trigger('click')
      await flushPromises()
      expect(wrapper.find('pre').text()).toContain('[REDACTED]')
    }
    fresh = false
    await wrapper.findAll('button').find((b) => b.text().includes('刷新证据状态')).trigger('click')
    await flushPromises()
    expect(wrapper.text()).toContain('过期/不可用')
    expect(wrapper.findAll('.evidence-summary')).toHaveLength(1)
    expect(fetchSpy).toHaveBeenCalledWith('/api/v1/aiops/runs/ledger-thread/evidence', { headers: expect.objectContaining({ Authorization: 'Bearer test-token' }) })
    wrapper.unmount()
  })

  it('sends Authorization header with SSE request', async () => {
    let capturedHeaders
    const fetchSpy = vi.spyOn(global, 'fetch').mockImplementation((url, options) => {
      capturedHeaders = options.headers
      return Promise.resolve({
        ok: true,
        body: new ReadableStream({
          start(controller) {
            controller.close()
          },
        }),
      })
    })

    const wrapper = mount(AIOps, {
      global: { plugins: [ElementPlus] },
    })
    await flushPromises()

    wrapper.vm.query = 'CPU 高'
    await flushPromises()
    const runButton = wrapper.findAll('button').find((b) => b.text().includes('开始诊断'))
    await runButton.trigger('click')
    await flushPromises()

    expect(capturedHeaders.Authorization).toBe('Bearer test-token')
    fetchSpy.mockRestore()
  })

  it('clears token and redirects to login on 401', async () => {
    const fetchSpy = vi.spyOn(global, 'fetch').mockResolvedValue({
      ok: false,
      status: 401,
      text: vi.fn().mockResolvedValue(JSON.stringify({ detail: 'Unauthorized' })),
    })

    const wrapper = mount(AIOps, {
      global: { plugins: [ElementPlus] },
    })
    await flushPromises()

    wrapper.vm.query = 'CPU 高'
    await flushPromises()
    const runButton = wrapper.findAll('button').find((b) => b.text().includes('开始诊断'))
    await runButton.trigger('click')
    await flushPromises()

    expect(localStorage.removeItem).toHaveBeenCalledWith('token')
    expect(window.location.href).toBe('/login')
    fetchSpy.mockRestore()
  })

  it('aborts active SSE stream when unmounted', async () => {
    let capturedSignal
    const fetchSpy = vi.spyOn(global, 'fetch').mockImplementation((url, options) => {
      capturedSignal = options?.signal
      // SSE stream stays open until aborted
      return Promise.resolve({
        ok: true,
        body: new ReadableStream({
          start(controller) {
            const check = () => {
              if (options?.signal?.aborted) {
                controller.close()
                return
              }
              setTimeout(check, 10)
            }
            check()
          },
        }),
      })
    })

    const wrapper = mount(AIOps, {
      global: { plugins: [ElementPlus] },
    })
    await flushPromises()

    wrapper.vm.query = 'CPU 高'
    await flushPromises()

    const buttons = wrapper.findAll('button')
    const runButton = buttons.find((b) => b.text().includes('开始诊断'))
    expect(runButton).toBeDefined()
    await runButton.trigger('click')
    await flushPromises()

    expect(capturedSignal).toBeDefined()
    expect(capturedSignal.aborted).toBe(false)

    wrapper.unmount()
    await flushPromises()

    expect(capturedSignal.aborted).toBe(true)
    fetchSpy.mockRestore()
  })

  it('restores a pending terminal approval on mount', async () => {
    localStorage.getItem.mockImplementation((key) => {
      if (key === 'token') return 'test-token'
      if (key === 'aiops_pending_thread') return 'thread-1'
      return null
    })

    const fetchSpy = vi.spyOn(global, 'fetch').mockResolvedValue({
      ok: true,
      json: vi.fn().mockResolvedValue({
        thread_id: 'thread-1',
        status: 'pending_terminal',
        terminal_approval: {
          command: 'uptime',
          expires_at: 1893456000000,
        },
        termcp_ui_url: 'http://127.0.0.1:18765',
      }),
    })

    const wrapper = mount(AIOps, {
      global: { plugins: [ElementPlus] },
    })
    await flushPromises()

    expect(fetchSpy).toHaveBeenCalledWith('/api/v1/aiops/runs/thread-1', {
      headers: expect.objectContaining({ Authorization: 'Bearer test-token' }),
    })
    expect(wrapper.text()).toContain('终端命令待审批')
    expect(wrapper.text()).toContain('uptime')
    expect(wrapper.findAll('button').some((b) => b.text().includes('继续诊断'))).toBe(true)
    fetchSpy.mockRestore()
  })

  it('clears pending approval after continue completes', async () => {
    localStorage.getItem.mockImplementation((key) => {
      if (key === 'token') return 'test-token'
      if (key === 'aiops_pending_thread') return 'thread-1'
      return null
    })

    const encoder = new TextEncoder()
    const fetchSpy = vi.spyOn(global, 'fetch').mockImplementation((url) => {
      if (url === '/api/v1/aiops/runs/thread-1') {
        return Promise.resolve({
          ok: true,
          json: vi.fn().mockResolvedValue({
            thread_id: 'thread-1',
            status: 'pending_terminal',
            terminal_approval: { command: 'uptime', expires_at: 1893456000000 },
            termcp_ui_url: 'http://127.0.0.1:18765',
          }),
        })
      }
      if (url === '/api/v1/aiops/runs/thread-1/continue') {
        return Promise.resolve({
          ok: true,
          body: new ReadableStream({
            start(controller) {
              controller.enqueue(encoder.encode('data: {"type":"complete","response":"诊断完成"}\n\n'))
              controller.close()
            },
          }),
        })
      }
      return Promise.reject(new Error(`unexpected url ${url}`))
    })

    const wrapper = mount(AIOps, {
      global: { plugins: [ElementPlus] },
    })
    await flushPromises()

    const continueButton = wrapper.findAll('button').find((b) => b.text().includes('继续诊断'))
    expect(continueButton).toBeDefined()
    await continueButton.trigger('click')
    await flushPromises()

    expect(wrapper.text()).not.toContain('终端命令待审批')
    expect(localStorage.removeItem).toHaveBeenCalledWith('aiops_pending_thread')
    expect(wrapper.text()).toContain('诊断完成')
    fetchSpy.mockRestore()
  })

  it('keeps pending approval when continue returns pending conflict', async () => {
    localStorage.getItem.mockImplementation((key) => {
      if (key === 'token') return 'test-token'
      if (key === 'aiops_pending_thread') return 'thread-1'
      return null
    })

    const fetchSpy = vi.spyOn(global, 'fetch').mockImplementation((url) => {
      if (url === '/api/v1/aiops/runs/thread-1') {
        return Promise.resolve({
          ok: true,
          json: vi.fn().mockResolvedValue({
            thread_id: 'thread-1',
            status: 'pending_terminal',
            terminal_approval: { command: 'uptime', expires_at: 1893456000000 },
            termcp_ui_url: 'http://127.0.0.1:18765',
          }),
        })
      }
      if (url === '/api/v1/aiops/runs/thread-1/continue') {
        return Promise.resolve({
          ok: false,
          status: 409,
          text: vi.fn().mockResolvedValue(JSON.stringify({ detail: '命令仍待 Termcp UI 审批' })),
        })
      }
      return Promise.reject(new Error(`unexpected url ${url}`))
    })

    const wrapper = mount(AIOps, {
      global: { plugins: [ElementPlus] },
    })
    await flushPromises()

    const continueButton = wrapper.findAll('button').find((b) => b.text().includes('继续诊断'))
    await continueButton.trigger('click')
    await flushPromises()

    expect(wrapper.text()).toContain('终端命令待审批')
    expect(wrapper.text()).toContain('uptime')
    expect(localStorage.removeItem).not.toHaveBeenCalledWith('aiops_pending_thread')
    fetchSpy.mockRestore()
  })
})
