import { describe, it, expect } from 'vitest'
import { mountWithPlugins } from '../test-utils'
import Dashboard from './Dashboard.vue'

describe('Dashboard.vue', () => {
  it('renders Chinese dashboard content', async () => {
    const wrapper = await mountWithPlugins(Dashboard)
    const text = wrapper.text()
    expect(text).toContain('工作台')
    expect(text).toContain('欢迎使用 AIOps 智能体平台')
    expect(text).toContain('管理知识库')
    expect(text).toContain('开始会话')
    expect(text).toContain('运行评测')
    expect(text).not.toContain('Dashboard')
    expect(text).not.toContain('Welcome to the AIOps Agent Platform')
    expect(text).not.toContain('Manage Knowledge Bases')
    expect(text).not.toContain('Start Chat')
    expect(text).not.toContain('Run Evaluation')
  })
})
