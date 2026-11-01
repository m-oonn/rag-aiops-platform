import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import ElementPlus, { ElMessage } from 'element-plus'
import AIOps from './AIOps.vue'

describe('AIOps.vue', () => {
  const investigation = { leading_id: 'h1', next_check: '检查下游监听',
    validation_issues: ['有限预期无效，保留原值且不参与假设保护或矛盾改向'],
    discriminating_question: '连接故障还是应用自身错误', expected_observation: '独立下游探测结果',
    observed_findings: [{ evidence_id: 'ev-123', summary: '入口返回503' }],
    evidence_summaries: [{ evidence_id: 'ev-123', summary: 'dependency_probe downstream: TCP ok, HTTP 200', collected_at: '2026-10-26T02:21:41Z' }],
    candidates: [{ id: 'h1', explanation: '下游连接异常', status: 'protected', relation: 'neutral', evidence_ids: ['ev-123'] }],
    events: [{ kind: 'hypothesis_protected', step: 2, hypothesis_id: 'h1', reason: '候选仍可核查' },
      { kind: 'contradiction_triggered', step: 3, hypothesis_id: 'h1', evidence_ids: ['ev-123'],
        reason: '新观察反驳原先预期', next_check: '检查下游监听' }] }

  it('restores saved investigation without granting raw evidence access', async () => {
    localStorage.getItem.mockImplementation(key => ({ token: 'test-token', aiops_last_thread: 'saved-run' })[key] || null)
    const fetchSpy = vi.spyOn(global, 'fetch').mockImplementation(async url => {
      if (url.endsWith('/saved-run')) return { ok: true, json: async () => ({ status: 'completed', report: '未定位', investigation }) }
      if (url.endsWith('/evidence')) return { ok: true, json: async () => ({ evidence: [{ evidence_id: 'ev-123', summary: 'TCP observation' }] }) }
      throw new Error(`unexpected ${url}`)
    })
    const wrapper = mount(AIOps, { attachTo: document.body, global: { plugins: [ElementPlus] } })
    await flushPromises()
    const panel = wrapper.find('.investigation-card')
    expect(panel.text()).toContain('保护期内')
    expect(panel.text()).toContain('下游连接异常')
    expect(panel.text()).toContain('反证触发改向')
    expect(panel.text()).toContain('连接故障还是应用自身错误')
    expect(panel.text()).toContain('本轮证据依据')
    expect(panel.text()).toContain('入口返回503')
    expect(panel.text()).toContain('本轮现场证据')
    expect(panel.text()).toContain('TCP ok, HTTP 200')
    expect(panel.text()).not.toContain('证据已截断')
    expect(panel.text()).not.toContain('采集返回错误')
    expect(panel.text()).toContain('候选仍可核查')
    expect(panel.text()).toContain('判断校验：有限预期无效，保留原值且不参与假设保护或矛盾改向')
    expect(wrapper.find('.el-collapse-item__header').attributes('aria-expanded')).toBe('false')
    const scroll = vi.fn()
    wrapper.find('#evidence-ev-123').element.scrollIntoView = scroll
    const refs = panel.findAll('button.investigation-evidence-ref')
    expect(refs).toHaveLength(2)
    for (const button of refs) {
      await button.trigger('click')
      await flushPromises()
      expect(wrapper.find('.el-collapse-item__header').attributes('aria-expanded')).toBe('true')
      expect(document.activeElement).toBe(wrapper.find('#evidence-ev-123').element)
    }
    expect(scroll).toHaveBeenCalledTimes(2)
    let afterFrame
    vi.stubGlobal('requestAnimationFrame', vi.fn(callback => { afterFrame = callback; return 1 }))
    await wrapper.find('.el-collapse-item__wrap').trigger('transitionend', { propertyName: 'max-height' })
    expect(scroll).toHaveBeenCalledTimes(2)
    afterFrame()
    expect(scroll).toHaveBeenCalledTimes(3)
    expect(scroll).toHaveBeenLastCalledWith({ behavior: 'instant', block: 'center' })
    await wrapper.find('.el-collapse-item__wrap').trigger('transitionend', { propertyName: 'padding-top' })
    expect(scroll).toHaveBeenCalledTimes(3)
    await wrapper.find('.el-collapse-item__wrap').trigger('transitionend', { propertyName: 'max-height' })
    wrapper.find('textarea').element.focus()
    afterFrame()
    expect(scroll).toHaveBeenCalledTimes(3)
    expect(fetchSpy.mock.calls.some(([url]) => url.endsWith('/evidence/ev-123'))).toBe(false)
    expect(wrapper.text()).not.toContain('查看现场证据')
    wrapper.unmount()
  })

  it('preserves a failed investigation report live and after refresh', async () => {
    const failure = { code: 'model_request_failed', message: '模型请求超时，调查未完成' }
    localStorage.getItem.mockImplementation(key => key === 'token' ? 'test-token' : null)
    let controller
    vi.spyOn(global, 'fetch').mockImplementation(async url => {
      if (url.endsWith('/failed-run')) return { ok: true, json: async () => ({ status: 'failed',
        report: '未定位根因：保留已有证据', investigation_failure: failure, investigation }) }
      if (url.endsWith('/evidence')) return { ok: true, json: async () => ({ evidence: [] }) }
      return { ok: true, body: new ReadableStream({ start(value) { controller = value } }) }
    })
    let wrapper = mount(AIOps, { global: { plugins: [ElementPlus] } })
    await wrapper.find('textarea').setValue('检查测试业务')
    await wrapper.findAll('button').find(b => b.text().includes('开始诊断')).trigger('click')
    await flushPromises()
    controller.enqueue(new TextEncoder().encode('data: ' + JSON.stringify({
      type: 'error', stage: 'investigation_failed', thread_id: 'failed-run',
      message: failure.message, investigation_failure: failure,
      response: '未定位根因：保留已有证据', investigation,
    }) + '\n\n'))
    controller.close()
    await flushPromises()
    expect(wrapper.text()).toContain(failure.message)
    expect(wrapper.find('.report-body').text()).toContain('保留已有证据')
    expect(wrapper.find('.el-alert--error').exists()).toBe(true)
    expect(localStorage.setItem).toHaveBeenCalledWith('aiops_last_thread', 'failed-run')
    expect(wrapper.text()).not.toContain('诊断完成')
    wrapper.unmount()
    localStorage.getItem.mockImplementation(key => ({ token: 'test-token', aiops_last_thread: 'failed-run' })[key] || null)
    wrapper = mount(AIOps, { global: { plugins: [ElementPlus] } })
    await flushPromises()
    expect(wrapper.text()).toContain(failure.message)
    expect(wrapper.find('.report-body').text()).toContain('保留已有证据')
    expect(wrapper.find('.el-alert--error').exists()).toBe(true)
    expect(wrapper.text()).not.toContain('诊断完成')
    wrapper.unmount()
  })

  it('shows incomplete collection and missing references without fetching raw content', async () => {
    localStorage.getItem.mockImplementation(key => ({ token: 'test-token', aiops_last_thread: 'saved-run' })[key] || null)
    const incomplete = { ...investigation, observed_findings: [{ summary: '缺少引用的旧发现' }],
      evidence_summaries: [
        { evidence_id: 'ev-missing', summary: '未取得日志', status: 'unavailable',
          truncated: true, error: '<img src=x onerror=alert(1)>' },
        { evidence_id: 'ev-not-applicable', summary: '事件日志不适用', status: 'not_applicable',
          error: 'no event channels configured' },
        { evidence_id: 'ev-partial', summary: '进程结果不完整', status: 'partial' },
        { evidence_id: 'ev-legacy-error', summary: '旧记录查询错误', error: 'AccessDenied' },
        { summary: '没有编号的旧记录' },
      ] }
    const fetchSpy = vi.spyOn(global, 'fetch').mockImplementation(async url => {
      if (url.endsWith('/saved-run')) return { ok: true, json: async () => ({ status: 'completed', report: '未定位', investigation: incomplete }) }
      if (url.endsWith('/evidence')) return { ok: true, json: async () => ({ evidence: [] }) }
      throw new Error(`unexpected ${url}`)
    })
    const wrapper = mount(AIOps, { global: { plugins: [ElementPlus] } })
    await flushPromises()
    const panel = wrapper.find('.investigation-card')
    expect(panel.text()).toContain('检查结果不可用：<img src=x onerror=alert(1)>')
    expect(panel.text()).toContain('该检查不适用于当前对象：no event channels configured')
    expect(panel.text()).toContain('证据仅包含部分结果')
    expect(panel.text()).toContain('检查返回错误：AccessDenied')
    expect(panel.text()).toContain('证据已截断，仅包含部分结果')
    expect(panel.find('img').exists()).toBe(false)
    expect(panel.text()).toContain('不能据此判定对象正常或异常')
    expect(panel.text()).toContain('缺少证据编号，无法定位原记录')
    expect(panel.text()).toContain('采集时间未知')
    const message = vi.spyOn(ElMessage, 'info')
    await panel.find('button.investigation-evidence-ref').trigger('click')
    await flushPromises()
    expect(message).toHaveBeenCalledWith('当前证据账本中未找到该引用，无法定位；请先刷新证据状态。')
    expect(fetchSpy.mock.calls.map(([url]) => url)).toEqual([
      '/api/v1/aiops/runs/saved-run', '/api/v1/aiops/runs/saved-run/evidence',
    ])
    wrapper.unmount()
  })

  it('replaces cumulative SSE investigation updates and clears them before a new run', async () => {
    localStorage.getItem.mockImplementation(key => key === 'token' ? 'test-token' : null)
    let streamController
    vi.spyOn(global, 'fetch').mockImplementation(async () => ({ ok: true, body: new ReadableStream({
      start(controller) { streamController = controller },
    }) }))
    const wrapper = mount(AIOps, { global: { plugins: [ElementPlus] } })
    await wrapper.find('textarea').setValue('检查测试业务')
    await wrapper.findAll('button').find(b => b.text().includes('开始诊断')).trigger('click')
    await flushPromises()
    const emit = (event) => streamController.enqueue(new TextEncoder().encode('data: ' + JSON.stringify(event) + '\n\n'))
    emit({ type: 'status', message: '继续核查', investigation })
    emit({ type: 'status', message: '继续核查', investigation })
    await flushPromises()
    expect(wrapper.find('.investigation-card').text()).toContain('下一检查：检查下游监听')
    expect(wrapper.findAll('.investigation-events > li')).toHaveLength(2)
    expect(wrapper.text()).not.toContain('诊断报告')
    emit({ type: 'complete', response: '未定位', investigation: { ...investigation, next_check: '', blocked_reason: '缺少可执行检查' } })
    streamController.close()
    await flushPromises()
    expect(wrapper.find('.investigation-card').text()).toContain('缺少可执行检查')
    await wrapper.findAll('button').find(b => b.text().includes('开始诊断')).trigger('click')
    await flushPromises()
    expect(wrapper.find('.investigation-card').exists()).toBe(false)
    streamController.close()
    await flushPromises()
    wrapper.unmount()
  })
  it.each([null, { version: 1, kind: 'localized_fault', scope: 'orders entry', target_id: 'windows-local-01',
    conclusion: '入口返回503，原因未明', stop_reason: '缺少下游证据',
    observed_findings: [{ evidence_id: 'ev-123', summary: '依赖 TCP 探测失败', collected_at: '2026-10-18T01:00:00Z' }],
    unresolved_questions: [{ id: 'q-1', question: '下游是否恢复', limitation: '6989监听采集失败：timeout',
      expected_observation: '同端口监听与进程归属', evidence_ids: ['ev-123'] }],
    limitations: ['downstream未提供允许服务/进程及日志映射'], validation_issues: ['因果解释未验证'],
    contradictions: ['日志为空，退出原因未知'],
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
        expect(wrapper.text()).toContain('6989监听采集失败：timeout')
        expect(wrapper.text()).toContain('预期观察：同端口监听与进程归属')
        expect(wrapper.find('.diagnosis-questions button').text()).toContain('ev-123')
        expect(wrapper.text()).toContain('限制/待核实说明：downstream未提供允许服务/进程及日志映射')
        expect(wrapper.text()).toContain('限制/待核实说明：日志为空，退出原因未知')
        expect(wrapper.text()).not.toContain('限制/矛盾：')
        expect(wrapper.text()).toContain('判断校验：因果解释未验证')
        expect(wrapper.findAll('button').some(b => b.text().includes('ev-123'))).toBe(true)
      } else expect(wrapper.text()).toContain('历史格式')
      expect(wrapper.find('.investigation-card').exists()).toBe(false)
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
