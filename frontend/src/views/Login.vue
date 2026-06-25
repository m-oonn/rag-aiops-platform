<template>
  <div class="login-container">
    <el-card class="box-card">
      <template #header>
        <div class="card-header">
          <span>{{ isRegister ? 'Register' : 'Login' }}</span>
        </div>
      </template>
      <el-form :model="form" label-width="80px">
        <el-form-item label="Username">
          <el-input v-model="form.username" />
        </el-form-item>
        <el-form-item label="Password">
          <el-input v-model="form.password" type="password" />
        </el-form-item>
        <el-form-item v-if="isRegister" label="Email">
          <el-input v-model="form.email" />
        </el-form-item>
        <el-form-item>
          <el-button type="primary" @click="submit">{{ isRegister ? 'Register' : 'Login' }}</el-button>
          <el-button @click="isRegister = !isRegister">{{ isRegister ? 'Switch to Login' : 'Switch to Register' }}</el-button>
        </el-form-item>
      </el-form>
    </el-card>
  </div>
</template>

<script setup>
import { ref, reactive } from 'vue'
import { useRouter } from 'vue-router'
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
      alert('Registration successful! Please login.')
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
    alert('Operation failed')
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
