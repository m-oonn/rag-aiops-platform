import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import ElementPlus from 'element-plus'
import AIOps from './AIOps.vue'

/** 现场取证前置条件：没有 Probe 就没有主机侧证据，花钱前必须先告知。 */
const mountWith = async (dependencies) => {
  vi.spyOn(global, 'fetch').mockImplementation(async (url) => {
    if (String(url).endsWith('/health/dependencies')) {
      return { ok: true, json: async () => dependencies }
    }
    if (String(url).endsWith('/runs/undefined')) {
      return { ok: false, json: async () => ({}) }
    }
    throw new Error(`unexpected request: ${url}`)
  })
  const wrapper = mount(AIOps, { global: { plugins: [ElementPlus] } })
  await flushPromises()
  return wrapper
}

const startButton = (wrapper) => wrapper.findAll('button').find((b) => b.text().includes('开始诊断'))

const fillQuery = async (wrapper) => {
  await wrapper.find('textarea').setValue('订单服务 5xx 突增，帮我定位原因')
}

describe('AIOps 现场取证前置条件', () => {
  beforeEach(() => {
    vi.stubGlobal('localStorage', {
      getItem: vi.fn(() => null),
      setItem: vi.fn(),
      removeItem: vi.fn(),
    })
    vi.stubGlobal('location', { href: '/aiops' })
  })
  afterEach(() => {
    vi.unstubAllGlobals()
    vi.restoreAllMocks()
  })

  it('Probe 未启用时先告知可能白花费用，并要求显式确认后才允许开始', async () => {
    const wrapper = await mountWith({
      services: {
        mcp_monitor: { status: 'ok', error: null },
        probe: { status: 'unavailable', error: 'connection refused' },
      },
      overall: 'degraded',
    })
    await fillQuery(wrapper)

    expect(wrapper.text()).toContain('现场取证能力受限')
    expect(wrapper.text()).toContain('Windows Probe 未启用或不可达')
    // 未确认前不能开始，否则用户会在不知情的情况下调用付费模型
    expect(startButton(wrapper).attributes('disabled')).toBeDefined()

    await wrapper.find('input[type="checkbox"]').setValue(true)
    expect(startButton(wrapper).attributes('disabled')).toBeUndefined()
  })

  it('取证工具全部不可用时给出更强的一档说明', async () => {
    const wrapper = await mountWith({
      services: {
        mcp_monitor: { status: 'unavailable', error: 'refused' },
        mcp_cls: { status: 'unavailable', error: 'refused' },
      },
      overall: 'degraded',
    })

    expect(wrapper.text()).toContain('现场取证工具当前全部不可用')
  })

  it('Probe 可用时不打扰用户，开始按钮直接可用', async () => {
    const wrapper = await mountWith({
      services: {
        mcp_monitor: { status: 'unavailable', error: 'refused' },
        probe: { status: 'ok', error: null },
      },
      overall: 'degraded',
    })
    await fillQuery(wrapper)

    expect(wrapper.text()).not.toContain('现场取证能力受限')
    expect(startButton(wrapper).attributes('disabled')).toBeUndefined()
  })

  it('依赖探测请求失败时不误报，仍然允许开始诊断', async () => {
    vi.spyOn(global, 'fetch').mockImplementation(async (url) => {
      if (String(url).endsWith('/health/dependencies')) throw new Error('network down')
      throw new Error(`unexpected request: ${url}`)
    })
    const wrapper = mount(AIOps, { global: { plugins: [ElementPlus] } })
    await flushPromises()
    await fillQuery(wrapper)

    expect(wrapper.text()).not.toContain('现场取证能力受限')
    expect(startButton(wrapper).attributes('disabled')).toBeUndefined()
  })
})