<template>
  <div>
    <h2>Dashboard</h2>
    <p>Welcome to the RAG System.</p>
    <el-row :gutter="20">
      <el-col :span="8">
        <el-card shadow="hover" @click="$router.push('/knowledge-bases')">
          Manage Knowledge Bases
        </el-card>
      </el-col>
      <el-col :span="8">
        <el-card shadow="hover" @click="$router.push('/chat')">
          Start Chat
        </el-card>
      </el-col>
      <el-col :span="8">
        <el-card shadow="hover" @click="$router.push('/evaluation')">
          Run Evaluation
        </el-card>
      </el-col>
    </el-row>
  </div>
</template>
