import { describe, it, expect } from 'vitest'
import { mountWithPlugins } from './test-utils'
import App from './App.vue'

describe('App.vue layout', () => {
  it('renders Chinese navigation and header', async () => {
    const wrapper = await mountWithPlugins(App, {
      route: '/dashboard',
      routes: [{ path: '/dashboard', component: { template: '<div>仪表盘内容</div>' } }],
    })

    const text = wrapper.text()
    expect(text).toContain('AIOps 智能体平台')
    expect(text).toContain('仪表盘')
    expect(text).toContain('会话')
    expect(text).toContain('知识库')
    expect(text).toContain('助手')
    expect(text).toContain('AIOps 诊断')
    expect(text).toContain('监控')
    expect(text).toContain('评测')
    expect(text).toContain('退出登录')
    expect(text).not.toContain('Dashboard')
    expect(text).not.toContain('Chat')
    expect(text).not.toContain('Knowledge Bases')
    expect(text).not.toContain('Assistants')
    expect(text).not.toContain('Monitor')
    expect(text).not.toContain('Evaluation')
    expect(text).not.toContain('Logout')
  })
})
