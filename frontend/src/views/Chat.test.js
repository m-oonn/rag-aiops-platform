import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import ElementPlus from 'element-plus'
import { createRouter, createWebHistory } from 'vue-router'
import Chat from './Chat.vue'
import api from '../api'

vi.mock('../api', () => ({
  default: {
    get: vi.fn(),
    post: vi.fn(),
    put: vi.fn(),
    delete: vi.fn(),
  }
}))

function createDeferred() {
  let resolve, reject
  const promise = new Promise((res, rej) => {
    resolve = res
    reject = rej
  })
  return { promise, resolve, reject }
}

async function mountChat() {
  const router = createRouter({
    history: createWebHistory(),
    routes: [{ path: '/', component: Chat }]
  })
  await router.push('/')
  await router.isReady()

  return mount(Chat, {
    global: { plugins: [ElementPlus, router] }
  })
}

describe('Chat.vue', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    vi.stubGlobal('localStorage', {
      getItem: vi.fn(() => 'test-token'),
      setItem: vi.fn(),
      removeItem: vi.fn(),
    })
    vi.stubGlobal('location', { href: '/chat' })
  })

  afterEach(() => {
    vi.unstubAllGlobals()
    vi.restoreAllMocks()
  })

  it('fetches KBs, assistants and sessions in parallel on mount', async () => {
    const kbDeferred = createDeferred()
    const assistantDeferred = createDeferred()
    const sessionDeferred = createDeferred()

    api.get.mockImplementation((url) => {
      if (url === '/knowledge-bases/') return kbDeferred.promise
      if (url === '/assistants/') return assistantDeferred.promise
      if (url === '/chat/sessions') return sessionDeferred.promise
      return Promise.resolve({ data: [] })
    })

    mountChat()

    // Allow the synchronous part of onMounted to schedule all three requests
    await new Promise((r) => setTimeout(r, 0))

    expect(api.get).toHaveBeenCalledWith('/knowledge-bases/')
    expect(api.get).toHaveBeenCalledWith('/assistants/')
    expect(api.get).toHaveBeenCalledWith('/chat/sessions')

    kbDeferred.resolve({ data: [] })
    assistantDeferred.resolve({ data: [] })
    sessionDeferred.resolve({ data: [] })
    await flushPromises()
  })

  it('sends Authorization header in stream request', async () => {
    api.get.mockResolvedValue({ data: [] })

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

    const wrapper = await mountChat()
    await flushPromises()

    wrapper.vm.inputQuery = 'hello'
    await flushPromises()
    const sendButton = wrapper.findAll('button').find((b) => b.text().includes('发送'))
    expect(sendButton).toBeDefined()
    await sendButton.trigger('click')
    await flushPromises()

    expect(capturedHeaders.Authorization).toBe('Bearer test-token')
    fetchSpy.mockRestore()
  })

  it('clears token and redirects to login when stream returns 401', async () => {
    api.get.mockResolvedValue({ data: [] })

    const fetchSpy = vi.spyOn(global, 'fetch').mockResolvedValue({
      ok: false,
      status: 401,
      text: vi.fn().mockResolvedValue(JSON.stringify({ detail: 'Unauthorized' })),
    })

    const wrapper = await mountChat()
    await flushPromises()

    wrapper.vm.inputQuery = 'hello'
    await flushPromises()
    const sendButton = wrapper.findAll('button').find((b) => b.text().includes('发送'))
    await sendButton.trigger('click')
    await flushPromises()

    expect(localStorage.removeItem).toHaveBeenCalledWith('token')
    expect(window.location.href).toBe('/login')
    fetchSpy.mockRestore()
  })

  it('aborts active stream when unmounted', async () => {
    api.get.mockResolvedValue({ data: [] })

    let capturedSignal
    const fetchSpy = vi.spyOn(global, 'fetch').mockImplementation((url, options) => {
      capturedSignal = options?.signal
      // Stream stays open until aborted so the controller remains active
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
          }
        })
      })
    })

    const wrapper = await mountChat()
    await flushPromises()

    // Start a stream by typing and submitting (no assistant/KB selected)
    wrapper.vm.inputQuery = 'hello'
    await flushPromises()
    const buttons = wrapper.findAll('button')
    const sendButton = buttons.find((b) => b.text().includes('发送'))
    expect(sendButton).toBeDefined()
    await sendButton.trigger('click')
    await flushPromises()

    expect(capturedSignal).toBeDefined()
    expect(capturedSignal.aborted).toBe(false)

    wrapper.unmount()
    await flushPromises()

    expect(capturedSignal.aborted).toBe(true)
    fetchSpy.mockRestore()
  })
})
