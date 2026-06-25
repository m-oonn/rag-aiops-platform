import { createRouter, createWebHistory } from 'vue-router'
import Login from '../views/Login.vue'
import Dashboard from '../views/Dashboard.vue'
import Chat from '../views/Chat.vue'
import KnowledgeBase from '../views/KnowledgeBase.vue'
import KnowledgeBaseDetail from '../views/KnowledgeBaseDetail.vue'
import Evaluation from '../views/Evaluation.vue'
import Assistant from '../views/Assistant.vue'
import Agent from '../views/Agent.vue'
import Monitor from '../views/Monitor.vue'

const routes = [
  { path: '/', redirect: '/dashboard' },
  { path: '/login', component: Login },
  { path: '/dashboard', component: Dashboard, meta: { requiresAuth: true } },
  { path: '/chat', component: Chat, meta: { requiresAuth: true } },
  { path: '/knowledge-bases', component: KnowledgeBase, meta: { requiresAuth: true } },
  { path: '/knowledge-bases/:id', component: KnowledgeBaseDetail, meta: { requiresAuth: true } },
  { path: '/evaluation', component: Evaluation, meta: { requiresAuth: true } },
  { path: '/assistants', component: Assistant, meta: { requiresAuth: true } },
  { path: '/agents', component: Agent, meta: { requiresAuth: true } },
  { path: '/monitor', component: Monitor, meta: { requiresAuth: true } },
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
