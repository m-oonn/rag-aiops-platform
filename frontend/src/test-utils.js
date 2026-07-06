import { mount } from '@vue/test-utils'
import ElementPlus from 'element-plus'
import { createRouter, createWebHistory } from 'vue-router'

/**
 * 为 Vue 组件测试提供公共挂载环境：ElementPlus + vue-router。
 */
export async function mountWithPlugins(Component, options = {}) {
  const routes = options.routes || [{ path: '/', component: Component }]
  const router = createRouter({
    history: createWebHistory(),
    routes
  })

  const initialRoute = options.route || '/'
  await router.push(initialRoute)
  await router.isReady()

  return mount(Component, {
    global: {
      plugins: [ElementPlus, router]
    },
    ...options.mountOptions
  })
}
