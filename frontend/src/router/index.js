import { createRouter, createWebHistory } from 'vue-router'

// 路由级懒加载：首屏只加载登录/工作台，其余页面（含 echarts 依赖）按访问时加载
const routes = [
  { path: '/', redirect: '/dashboard' },
  { path: '/login', component: () => import('../views/Login.vue') },
  { path: '/dashboard', component: () => import('../views/Dashboard.vue'), meta: { requiresAuth: true } },
  { path: '/chat', component: () => import('../views/Chat.vue'), meta: { requiresAuth: true } },
  { path: '/knowledge-bases', component: () => import('../views/KnowledgeBase.vue'), meta: { requiresAuth: true } },
  { path: '/knowledge-bases/:id', component: () => import('../views/KnowledgeBaseDetail.vue'), meta: { requiresAuth: true } },
  { path: '/evaluation', component: () => import('../views/Evaluation.vue'), meta: { requiresAuth: true } },
  { path: '/assistants', component: () => import('../views/Assistant.vue'), meta: { requiresAuth: true } },
  { path: '/agents', component: () => import('../views/Agent.vue'), meta: { requiresAuth: true } },
  { path: '/aiops', component: () => import('../views/AIOps.vue'), meta: { requiresAuth: true } },
  { path: '/monitor', component: () => import('../views/Monitor.vue'), meta: { requiresAuth: true } },
  { path: '/queue-monitor', component: () => import('../views/QueueMonitor.vue'), meta: { requiresAuth: true } },
]

const router = createRouter({
  history: createWebHistory(),
  routes,
})

router.beforeEach((to, from, next) => {
  const token = localStorage.getItem('token')
  if (to.meta.requiresAuth && !token) {
    next('/login')
  } else {
    next()
  }
})

export default router
