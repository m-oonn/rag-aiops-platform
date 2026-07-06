<template>
  <div class="login-container">
    <el-card class="box-card">
      <template #header>
        <div class="card-header">
          <span>{{ isRegister ? '注册' : '登录' }}</span>
        </div>
      </template>
      <el-form :model="form" label-width="80px">
        <el-form-item label="用户名">
          <el-input v-model="form.username" />
        </el-form-item>
        <el-form-item label="密码">
          <el-input v-model="form.password" type="password" />
        </el-form-item>
        <el-form-item v-if="isRegister" label="邮箱">
          <el-input v-model="form.email" />
        </el-form-item>
        <el-form-item>
          <el-button type="primary" @click="submit">{{ isRegister ? '注册' : '登录' }}</el-button>
          <el-button @click="isRegister = !isRegister">{{ isRegister ? '切换登录' : '切换注册' }}</el-button>
        </el-form-item>
      </el-form>
    </el-card>
  </div>
</template>

<script setup>
import { ref, reactive } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import api from '../api'

const router = useRouter()
const isRegister = ref(false)
const form = reactive({
  username: '',
  password: '',
  email: ''
})

const submit = async () => {
  try {
    if (isRegister.value) {
      await api.post('/auth/register', form)
      isRegister.value = false
      ElMessage.success('注册成功，请登录')
    } else {
      const formData = new FormData()
      formData.append('username', form.username)
      formData.append('password', form.password)
      const res = await api.post('/auth/login/access-token', formData)
      localStorage.setItem('token', res.data.access_token)
      localStorage.setItem('username', form.username)
      router.push('/dashboard')
    }
  } catch (err) {
    console.error(err)
    const detail = err?.response?.data?.detail
    const message = detail || err.message || '操作失败'
    ElMessage.error(message)
  }
}
</script>

<style scoped>
.login-container {
  display: flex;
  justify-content: center;
  align-items: center;
  height: 100vh;
}
.box-card {
  width: 400px;
}
</style>
