<template>
  <div>
    <PageHeader title="用户管理" subtitle="分配管理员与审计角色：审计角色可查看 AIOps 证据原文" />

    <el-alert
      v-if="error"
      :title="error"
      type="error"
      show-icon
      :closable="false"
      style="margin-bottom: 16px"
    />

    <div class="filter-bar">
      <el-input
        v-model="keyword"
        placeholder="按用户名或邮箱过滤"
        clearable
        style="max-width: 260px"
      />
      <div style="flex: 1"></div>
      <el-button icon="Refresh" @click="fetchUsers">刷新</el-button>
    </div>

    <el-table :data="filteredUsers" style="width: 100%" v-loading="loading">
      <el-table-column prop="id" label="ID" width="80" />
      <el-table-column prop="username" label="用户名">
        <template #default="scope">
          <span>{{ scope.row.username }}</span>
          <el-tag v-if="scope.row.id === currentUserId" size="small" style="margin-left: 8px">当前账号</el-tag>
        </template>
      </el-table-column>
      <el-table-column prop="email" label="邮箱" />
      <el-table-column prop="is_active" label="状态" width="100">
        <template #default="scope">
          <el-tag :type="scope.row.is_active ? 'success' : 'info'">
            {{ scope.row.is_active ? '启用' : '停用' }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column label="角色" width="180">
        <template #default="scope">
          <el-select
            v-model="scope.row.role"
            size="small"
            :disabled="scope.row.id === currentUserId"
            @change="(value) => changeRole(scope.row, value)"
          >
            <el-option label="普通用户" value="user" />
            <el-option label="审计" value="auditor" />
            <el-option label="管理员" value="admin" />
          </el-select>
        </template>
      </el-table-column>
    </el-table>

    <el-alert
      type="info"
      :closable="false"
      show-icon
      style="margin-top: 16px"
      title="角色说明"
    >
      <div>普通用户：使用问答、知识库、诊断等常规功能。</div>
      <div>审计：在普通用户之上，可读取 AIOps 诊断证据的原文片段（can_read_raw）。</div>
      <div>管理员：在审计之上，可在此页调整他人角色。不能修改自己的角色，避免最后一个管理员被降级后无人可管。</div>
    </el-alert>
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import api from '../api'
import PageHeader from '../components/PageHeader.vue'

const users = ref([])
const loading = ref(false)
const error = ref('')
const keyword = ref('')
const currentUserId = ref(null)

const filteredUsers = computed(() => {
  const q = keyword.value.trim().toLowerCase()
  if (!q) return users.value
  return users.value.filter(
    (u) => u.username?.toLowerCase().includes(q) || u.email?.toLowerCase().includes(q)
  )
})

const fetchUsers = async () => {
  loading.value = true
  error.value = ''
  try {
    const { data } = await api.get('/auth/users')
    users.value = data
  } catch (e) {
    const status = e?.response?.status
    error.value = status === 403
      ? '需要管理员权限才能查看用户列表'
      : (e?.response?.data?.detail || '获取用户列表失败')
  } finally {
    loading.value = false
  }
}

const fetchCurrentUser = async () => {
  try {
    const { data } = await api.get('/auth/me')
    currentUserId.value = data.id
    localStorage.setItem('role', data.role || 'user')
  } catch {
    // 角色读取失败不影响列表本身的功能
  }
}

const changeRole = async (row, role) => {
  try {
    const { data } = await api.patch(`/auth/users/${row.id}/role`, { role })
    Object.assign(row, data)
    ElMessage.success(`已把 ${data.username} 设为 ${roleLabel(data.role)}`)
  } catch (e) {
    // 失败时不猜服务端状态，直接重拉列表
    ElMessage.error(e?.response?.data?.detail || '修改角色失败')
    await fetchUsers()
  }
}

const roleLabel = (role) => ({ user: '普通用户', auditor: '审计', admin: '管理员' }[role] || role)

onMounted(() => {
  fetchCurrentUser()
  fetchUsers()
})
</script>