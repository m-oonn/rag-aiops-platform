import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { getAuthHeaders, handleAuthError, parseFetchError } from './auth'

describe('auth utils', () => {
  let originalLocation

  beforeEach(() => {
    originalLocation = window.location
    vi.stubGlobal('localStorage', {
      getItem: vi.fn(),
      setItem: vi.fn(),
      removeItem: vi.fn(),
    })
    vi.stubGlobal('location', { href: '/aiops' })
  })

  afterEach(() => {
    vi.unstubAllGlobals()
    vi.restoreAllMocks()
  })

  describe('getAuthHeaders', () => {
    it('adds Authorization when token exists', () => {
      localStorage.getItem.mockReturnValue('my-token')
      expect(getAuthHeaders()).toEqual({
        'Content-Type': 'application/json',
        Authorization: 'Bearer my-token',
      })
    })

    it('does not add Authorization when token is absent', () => {
      localStorage.getItem.mockReturnValue(null)
      expect(getAuthHeaders()).toEqual({
        'Content-Type': 'application/json',
      })
    })
  })

  describe('handleAuthError', () => {
    it('clears token, redirects and returns true on 401', () => {
      const showMessage = vi.fn()
      const result = handleAuthError(401, { showMessage })

      expect(result).toBe(true)
      expect(localStorage.removeItem).toHaveBeenCalledWith('token')
      expect(showMessage).toHaveBeenCalledWith('登录已过期，请重新登录')
      expect(window.location.href).toBe('/login')
    })

    it('uses custom message and loginUrl when provided', () => {
      const showMessage = vi.fn()
      handleAuthError(401, {
        showMessage,
        message: '请重新登录',
        loginUrl: '/signin',
      })

      expect(showMessage).toHaveBeenCalledWith('请重新登录')
      expect(window.location.href).toBe('/signin')
    })

    it('returns false and does nothing for non-401 status', () => {
      const showMessage = vi.fn()
      const result = handleAuthError(500, { showMessage })

      expect(result).toBe(false)
      expect(localStorage.removeItem).not.toHaveBeenCalled()
      expect(showMessage).not.toHaveBeenCalled()
      expect(window.location.href).toBe('/aiops')
    })
  })

  describe('parseFetchError', () => {
    it('extracts detail from JSON body', async () => {
      const res = {
        status: 400,
        statusText: 'Bad Request',
        text: vi.fn().mockResolvedValue(JSON.stringify({ detail: '参数错误' })),
      }
      const err = await parseFetchError(res)
      expect(err).toEqual({ status: 400, detail: '参数错误' })
    })

    it('falls back to raw text when detail is absent', async () => {
      const res = {
        status: 500,
        statusText: 'Internal Server Error',
        text: vi.fn().mockResolvedValue('raw body'),
      }
      const err = await parseFetchError(res)
      expect(err).toEqual({ status: 500, detail: 'raw body' })
    })

    it('falls back to raw text when body is not valid JSON', async () => {
      const res = {
        status: 502,
        statusText: 'Bad Gateway',
        text: vi.fn().mockResolvedValue('<html>bad gateway</html>'),
      }
      const err = await parseFetchError(res)
      expect(err).toEqual({ status: 502, detail: '<html>bad gateway</html>' })
    })

    it('falls back to statusText when body is empty', async () => {
      const res = {
        status: 503,
        statusText: 'Service Unavailable',
        text: vi.fn().mockResolvedValue(''),
      }
      const err = await parseFetchError(res)
      expect(err).toEqual({ status: 503, detail: 'Service Unavailable' })
    })
  })
})
