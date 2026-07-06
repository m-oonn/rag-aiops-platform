import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import ElementPlus from 'element-plus'
import AIOps from './AIOps.vue'

describe('AIOps.vue', () => {
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
})
