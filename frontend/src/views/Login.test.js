import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { flushPromises } from '@vue/test-utils'
import { mountWithPlugins } from '../test-utils'
import Login from './Login.vue'
import api from '../api'

vi.mock('../api', () => ({
  default: {
    get: vi.fn(),
    post: vi.fn(),
    put: vi.fn(),
    delete: vi.fn()
  }
}))

describe('Login.vue', () => {
  let storage = {}

  beforeEach(() => {
    storage = {}
    vi.spyOn(global.Storage.prototype, 'setItem').mockImplementation((key, value) => {
      storage[key] = value
    })
    vi.clearAllMocks()
  })

  afterEach(() => {
    vi.restoreAllMocks()
  })

  it('logs in and redirects to dashboard on success', async () => {
    api.post.mockResolvedValue({ data: { access_token: 'fake-token' } })

    const wrapper = await mountWithPlugins(Login)
    await flushPromises()

    await wrapper.find('input[type="text"]').setValue('admin')
    await wrapper.find('input[type="password"]').setValue('password')

    const submitButton = wrapper.findAll('button').find((b) => b.text() === '登录')
    await submitButton.trigger('click')
    await flushPromises()

    expect(api.post).toHaveBeenCalledWith('/auth/login/access-token', expect.any(FormData))
    const postedFormData = api.post.mock.calls[0][1]
    expect(postedFormData.get('username')).toBe('admin')
    expect(postedFormData.get('password')).toBe('password')

    expect(storage.token).toBe('fake-token')
    expect(storage.username).toBe('admin')
    expect(wrapper.vm.$route.path).toBe('/dashboard')
  })

  it('shows error message on login failure', async () => {
    api.post.mockRejectedValue({ response: { data: { detail: 'Invalid credentials' } } })

    const wrapper = await mountWithPlugins(Login)
    await flushPromises()

    await wrapper.find('input[type="text"]').setValue('admin')
    await wrapper.find('input[type="password"]').setValue('wrong')

    const submitButton = wrapper.findAll('button').find((b) => b.text() === '登录')
    await submitButton.trigger('click')
    await flushPromises()

    expect(api.post).toHaveBeenCalledWith('/auth/login/access-token', expect.any(FormData))
  })

  it('switches to register form and submits registration', async () => {
    api.post.mockResolvedValue({ data: {} })

    const wrapper = await mountWithPlugins(Login)
    await flushPromises()

    const switchButton = wrapper.findAll('button').find((b) => b.text() === '切换注册')
    await switchButton.trigger('click')
    await flushPromises()

    await wrapper.find('input[type="text"]').setValue('newuser')
    await wrapper.find('input[type="password"]').setValue('pass')
    const inputs = wrapper.findAll('input')
    await inputs[2].setValue('newuser@example.com')

    const registerButton = wrapper.findAll('button').find((b) => b.text() === '注册')
    await registerButton.trigger('click')
    await flushPromises()

    expect(api.post).toHaveBeenCalledWith('/auth/register', expect.any(Object))
    expect(wrapper.vm.isRegister).toBe(false)
  })
})
