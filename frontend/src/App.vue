<template>
  <el-container class="layout-container">
    <el-aside width="200px" v-if="!isLoginPage">
      <el-menu router :default-active="$route.path" class="el-menu-vertical-demo">
        <el-menu-item index="/dashboard">
          <el-icon><Menu /></el-icon>
          <span>Dashboard</span>
        </el-menu-item>
        <el-menu-item index="/chat">
          <el-icon><ChatDotRound /></el-icon>
          <span>Chat</span>
        </el-menu-item>
        <el-menu-item index="/knowledge-bases">
          <el-icon><Document /></el-icon>
          <span>Knowledge Bases</span>
        </el-menu-item>
        <el-menu-item index="/assistants">
          <el-icon><User /></el-icon>
          <span>Assistants</span>
        </el-menu-item>
        <!-- <el-menu-item index="/agents">
          <el-icon><Cpu /></el-icon>
          <span>Agents</span>
        </el-menu-item> -->
        <el-menu-item index="/monitor">
          <el-icon><Monitor /></el-icon>
          <span>Monitor</span>
        </el-menu-item>
        <el-menu-item index="/evaluation">
          <el-icon><DataAnalysis /></el-icon>
          <span>Evaluation</span>
        </el-menu-item>
        <el-menu-item @click="logout">
          <el-icon><SwitchButton /></el-icon>
          <span>Logout</span>
        </el-menu-item>
      </el-menu>
    </el-aside>
    <el-container>
      <el-header v-if="!isLoginPage">
        <div class="header-content">
          <h2>RAG System</h2>
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
const username = ref(localStorage.getItem('username') || 'User')

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
