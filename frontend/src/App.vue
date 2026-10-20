<template>
  <el-container class="layout-container">
    <el-aside :width="asideWidth" v-if="!isLoginPage" class="app-aside">
      <el-menu
        router
        :default-active="$route.path"
        :collapse="isCollapse"
        :collapse-transition="false"
        class="app-menu"
      >
        <el-menu-item index="/dashboard">
          <el-icon><Menu /></el-icon>
          <template #title><span>仪表盘</span></template>
        </el-menu-item>
        <el-menu-item index="/chat">
          <el-icon><ChatDotRound /></el-icon>
          <template #title><span>会话</span></template>
        </el-menu-item>
        <el-menu-item index="/knowledge-bases">
          <el-icon><Document /></el-icon>
          <template #title><span>知识库</span></template>
        </el-menu-item>
        <el-menu-item index="/assistants">
          <el-icon><User /></el-icon>
          <template #title><span>助手</span></template>
        </el-menu-item>
        <el-menu-item index="/agents">
          <el-icon><Cpu /></el-icon>
          <template #title><span>Agents</span></template>
        </el-menu-item>
        <el-menu-item index="/aiops">
          <el-icon><DataAnalysis /></el-icon>
          <template #title><span>AIOps 诊断</span></template>
        </el-menu-item>
        <el-menu-item index="/monitor">
          <el-icon><Monitor /></el-icon>
          <template #title><span>监控</span></template>
        </el-menu-item>
        <el-menu-item index="/queue-monitor">
          <el-icon><Odometer /></el-icon>
          <template #title><span>队列监控</span></template>
        </el-menu-item>
        <el-menu-item index="/evaluation">
          <el-icon><TrendCharts /></el-icon>
          <template #title><span>评测</span></template>
        </el-menu-item>
      </el-menu>
      <!-- 退出登录不属于导航项：el-menu 的 router 模式会把带 index 的项当成路由跳转，
           故放在 menu 之外，避免误跳 /logout 并消除 "Missing required prop: index" 告警 -->
      <div class="logout-item" @click="logout">
        <el-icon><SwitchButton /></el-icon>
        <span v-show="!isCollapse">退出登录</span>
      </div>
    </el-aside>
    <el-container>
      <el-header v-if="!isLoginPage" class="app-header">
        <div class="header-content">
          <div class="header-left">
            <el-button
              text
              class="collapse-btn"
              :title="isCollapse ? '展开导航' : '收起导航'"
              @click="isCollapse = !isCollapse"
            >
              <el-icon :size="18"><Expand v-if="isCollapse" /><Fold v-else /></el-icon>
            </el-button>
            <h2 class="app-title">AIOps 智能体平台</h2>
          </div>
          <el-tooltip :content="username" placement="bottom">
            <el-avatar>
              <el-icon><User /></el-icon>
            </el-avatar>
          </el-tooltip>
        </div>
      </el-header>
      <el-main class="app-main">
        <router-view />
      </el-main>
    </el-container>
  </el-container>
</template>

<script setup>
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { Expand, Fold } from '@element-plus/icons-vue'

const route = useRoute()
const router = useRouter()
const username = ref(localStorage.getItem('username') || '用户')

const isLoginPage = computed(() => route.path === '/login' || route.path === '/register')
const isCollapse = ref(false)
const asideWidth = computed(() => (isCollapse.value ? 'var(--app-sidebar-collapsed)' : 'var(--app-sidebar-width)'))

let mediaQuery = null
const applyCollapse = (event) => {
  isCollapse.value = event.matches
}

onMounted(() => {
  // jsdom/老环境没有 matchMedia：此时保持默认展开，不阻断渲染
  if (typeof window.matchMedia !== 'function') return
  mediaQuery = window.matchMedia('(max-width: 1024px)')
  isCollapse.value = mediaQuery.matches
  mediaQuery.addEventListener?.('change', applyCollapse)
})

onUnmounted(() => {
  mediaQuery?.removeEventListener?.('change', applyCollapse)
})

const logout = () => {
  localStorage.removeItem('token')
  localStorage.removeItem('username')
  router.push('/login')
}
</script>

<style>
.layout-container {
  height: 100vh;
}
.app-aside {
  display: flex;
  flex-direction: column;
  background: #fff;
  border-right: 1px solid var(--app-border-subtle);
  transition: width 0.2s ease;
  overflow: hidden;
}
.app-menu {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  overflow-x: hidden;
  border-right: none;
}
.logout-item {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  height: 56px;
  padding: 0 12px;
  cursor: pointer;
  color: var(--app-text-primary);
  border-top: 1px solid var(--app-border-subtle);
  white-space: nowrap;
}
.logout-item:hover {
  background-color: var(--el-color-primary-light-9);
  color: var(--el-color-primary);
}
.app-header {
  height: 56px;
  background: #fff;
  border-bottom: 1px solid var(--app-border-subtle);
}
.header-content {
  display: flex;
  justify-content: space-between;
  align-items: center;
  height: 56px;
}
.header-left {
  display: flex;
  align-items: center;
  gap: 8px;
  min-width: 0;
}
.collapse-btn {
  padding: 4px;
  color: var(--app-text-secondary);
}
.app-title {
  margin: 0;
  font-size: 16px;
  font-weight: 600;
  color: var(--app-text-primary);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.app-main {
  padding: var(--app-gap-page);
  overflow-y: auto;
}
@media (max-width: 640px) {
  .app-main {
    padding: var(--app-gap-inline);
  }
  .app-title {
    display: none;
  }
}
</style>
