import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { streamSSE } from './sse'

// 用给定的 chunk 字符串数组构造一个可读流
function makeStreamBody(chunks) {
  const encoder = new TextEncoder()
  let i = 0
  return {
    getReader() {
      return {
        read() {
          if (i < chunks.length) {
            const value = encoder.encode(chunks[i])
            i += 1
            return Promise.resolve({ value, done: false })
          }
          return Promise.resolve({ value: undefined, done: true })
        },
      }
    },
  }
}

describe('streamSSE', () => {
  beforeEach(() => {
    vi.stubGlobal('localStorage', {
      getItem: vi.fn(() => 'test-token'),
      setItem: vi.fn(),
      removeItem: vi.fn(),
    })
    vi.stubGlobal('location', { href: '/somewhere' })
  })

  afterEach(() => {
    vi.unstubAllGlobals()
    vi.restoreAllMocks()
  })

  it('sends Authorization header and posts JSON body', async () => {
    let capturedUrl, capturedOptions
    vi.spyOn(global, 'fetch').mockImplementation((url, options) => {
      capturedUrl = url
      capturedOptions = options
      return Promise.resolve({ ok: true, body: makeStreamBody([]) })
    })

    await streamSSE('/api/v1/x', { query: 'hi' }, { onEvent: vi.fn() })

    expect(capturedUrl).toBe('/api/v1/x')
    expect(capturedOptions.method).toBe('POST')
    expect(capturedOptions.headers.Authorization).toBe('Bearer test-token')
    expect(JSON.parse(capturedOptions.body)).toEqual({ query: 'hi' })
  })

  it('parses frames split by blank line and calls onEvent per frame', async () => {
    vi.spyOn(global, 'fetch').mockResolvedValue({
      ok: true,
      body: makeStreamBody([
        'data: {"type":"token","content":"a"}\n\n',
        'data: {"type":"token","content":"b"}\n\n',
      ]),
    })

    const events = []
    await streamSSE('/x', {}, { onEvent: (e) => events.push(e) })

    expect(events).toEqual([
      { type: 'token', content: 'a' },
      { type: 'token', content: 'b' },
    ])
  })

  it('normalizes \\r\\n line separators before framing', async () => {
    vi.spyOn(global, 'fetch').mockResolvedValue({
      ok: true,
      body: makeStreamBody(['data: {"type":"done"}\r\n\r\n']),
    })

    const events = []
    await streamSSE('/x', {}, { onEvent: (e) => events.push(e) })

    expect(events).toEqual([{ type: 'done' }])
  })

  it('reassembles frames spanning multiple chunks', async () => {
    vi.spyOn(global, 'fetch').mockResolvedValue({
      ok: true,
      body: makeStreamBody(['data: {"type":"to', 'ken","content":"x"}\n\n']),
    })

    const events = []
    await streamSSE('/x', {}, { onEvent: (e) => events.push(e) })

    expect(events).toEqual([{ type: 'token', content: 'x' }])
  })

  it('warns and continues on an unparseable frame', async () => {
    const warnSpy = vi.spyOn(console, 'warn').mockImplementation(() => {})
    vi.spyOn(global, 'fetch').mockResolvedValue({
      ok: true,
      body: makeStreamBody(['data: not-json\n\n', 'data: {"type":"ok"}\n\n']),
    })

    const events = []
    await streamSSE('/x', {}, { onEvent: (e) => events.push(e) })

    expect(warnSpy).toHaveBeenCalledWith('无法解析 SSE 帧:', 'not-json')
    expect(events).toEqual([{ type: 'ok' }])
  })

  it('clears token and redirects on 401', async () => {
    vi.spyOn(global, 'fetch').mockResolvedValue({
      ok: false,
      status: 401,
      text: vi.fn().mockResolvedValue(JSON.stringify({ detail: 'Unauthorized' })),
    })
    const showMessage = vi.fn()

    await expect(
      streamSSE('/x', {}, { onEvent: vi.fn(), showMessage })
    ).rejects.toThrow('HTTP 401')

    expect(localStorage.removeItem).toHaveBeenCalledWith('token')
    expect(window.location.href).toBe('/login')
    expect(showMessage).toHaveBeenCalled()
  })

  it('throws on non-ok response without a body', async () => {
    vi.spyOn(global, 'fetch').mockResolvedValue({
      ok: false,
      status: 500,
      text: vi.fn().mockResolvedValue('boom'),
    })

    await expect(streamSSE('/x', {}, { onEvent: vi.fn() })).rejects.toThrow(
      'HTTP 500'
    )
  })

  it('throws when response has no stream body', async () => {
    vi.spyOn(global, 'fetch').mockResolvedValue({ ok: true, body: null })

    await expect(streamSSE('/x', {}, { onEvent: vi.fn() })).rejects.toThrow(
      '服务器未返回数据流'
    )
  })
})
