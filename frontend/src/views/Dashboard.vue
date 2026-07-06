<template>
  <div>
    <h2>工作台</h2>
    <p>欢迎使用 AIOps 智能体平台。</p>
    <el-row :gutter="20">
      <el-col :span="8">
        <el-card shadow="hover" @click="$router.push('/knowledge-bases')">
          管理知识库
        </el-card>
      </el-col>
      <el-col :span="8">
        <el-card shadow="hover" @click="$router.push('/chat')">
          开始会话
        </el-card>
      </el-col>
      <el-col :span="8">
        <el-card shadow="hover" @click="$router.push('/evaluation')">
          运行评测
        </el-card>
      </el-col>
    </el-row>
  </div>
</template>
