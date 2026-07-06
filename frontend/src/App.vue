<template>
  <el-container class="layout-container">
    <el-aside width="200px" v-if="!isLoginPage">
      <el-menu router :default-active="$route.path" class="el-menu-vertical-demo">
        <el-menu-item index="/dashboard">
          <el-icon><Menu /></el-icon>
          <span>仪表盘</span>
        </el-menu-item>
        <el-menu-item index="/chat">
          <el-icon><ChatDotRound /></el-icon>
          <span>会话</span>
        </el-menu-item>
        <el-menu-item index="/knowledge-bases">
          <el-icon><Document /></el-icon>
          <span>知识库</span>
        </el-menu-item>
        <el-menu-item index="/assistants">
          <el-icon><User /></el-icon>
          <span>助手</span>
        </el-menu-item>
        <!-- <el-menu-item index="/agents">
          <el-icon><Cpu /></el-icon>
          <span>Agents</span>
        </el-menu-item> -->
        <el-menu-item index="/aiops">
          <el-icon><Cpu /></el-icon>
          <span>AIOps 诊断</span>
        </el-menu-item>
        <el-menu-item index="/monitor">
          <el-icon><Monitor /></el-icon>
          <span>监控</span>
        </el-menu-item>
        <el-menu-item index="/queue-monitor">
          <el-icon><Monitor /></el-icon>
          <span>队列监控</span>
        </el-menu-item>
        <el-menu-item index="/evaluation">
          <el-icon><DataAnalysis /></el-icon>
          <span>评测</span>
        </el-menu-item>
        <el-menu-item @click="logout">
          <el-icon><SwitchButton /></el-icon>
          <span>退出登录</span>
        </el-menu-item>
      </el-menu>
    </el-aside>
    <el-container>
      <el-header v-if="!isLoginPage">
        <div class="header-content">
          <h2>AIOps 智能体平台</h2>
          <el-tooltip :content="username" placement="bottom">
             <el-avatar>
                <el-icon><User /></el-icon>
             </el-avatar>
          </el-tooltip>
        </div>
      </el-header>
      <el-main>
        <router-view />
      </el-main>
    </el-container>
  </el-container>
</template>

<script setup>
import { computed, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'

const route = useRoute()
const router = useRouter()
const username = ref(localStorage.getItem('username') || '用户')

const isLoginPage = computed(() => route.path === '/login' || route.path === '/register')

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
.el-menu-vertical-demo {
  height: 100%;
}
.header-content {
  display: flex;
  justify-content: space-between;
  align-items: center;
}
</style>
