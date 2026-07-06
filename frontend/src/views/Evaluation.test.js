import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import ElementPlus from 'element-plus'
import Evaluation from './Evaluation.vue'
import api from '../api'

vi.mock('../api', () => ({
  default: {
    get: vi.fn(),
    post: vi.fn(),
    put: vi.fn(),
    delete: vi.fn(),
  }
}))

describe('Evaluation.vue', () => {
  const setIntervalSpy = vi.spyOn(global, 'setInterval')
  const clearIntervalSpy = vi.spyOn(global, 'clearInterval')

  beforeEach(() => {
    api.get.mockResolvedValue({ data: [] })
    api.post.mockResolvedValue({ data: {} })
    setIntervalSpy.mockClear()
    clearIntervalSpy.mockClear()
  })

  afterEach(() => {
    vi.restoreAllMocks()
  })

  it('clears the task polling interval when unmounted', async () => {
    const wrapper = mount(Evaluation, {
      global: {
        plugins: [ElementPlus]
      }
    })
    await flushPromises()

    const evalCalls = setIntervalSpy.mock.calls.filter((call) => call[1] === 5000)
    expect(evalCalls.length).toBeGreaterThanOrEqual(1)
    const intervalId = setIntervalSpy.mock.results[
      setIntervalSpy.mock.calls.findIndex((call) => call[1] === 5000)
    ].value

    wrapper.unmount()
    await flushPromises()

    expect(clearIntervalSpy).toHaveBeenCalledWith(intervalId)
  })
})
