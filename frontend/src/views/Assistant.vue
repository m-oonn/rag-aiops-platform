<template>
  <div>
    <h2>助手管理</h2>
    <el-button type="primary" @click="openDialog()">创建助手</el-button>
    
    <el-table :data="assistants" style="width: 100%; margin-top: 20px;">
      <el-table-column prop="name" label="名称" width="180" />
      <el-table-column prop="description" label="描述" />
      <el-table-column prop="llm_model" label="模型" />
      <el-table-column label="操作">
        <template #default="scope">
          <el-button size="small" @click="startChat(scope.row)">会话</el-button>
          <el-button size="small" @click="openDialog(scope.row)">编辑</el-button>
          <el-button size="small" type="danger" @click="deleteAssistant(scope.row.id)">删除</el-button>
        </template>
      </el-table-column>
    </el-table>

    <el-dialog v-model="dialogVisible" :title="isEdit ? '编辑助手' : '创建助手'" width="60%">
      <el-form :model="form" label-width="140px">
        <el-tabs v-model="activeTab">
            <el-tab-pane label="基本信息" name="basic">
                <el-form-item label="名称">
                  <el-input v-model="form.name" />
                </el-form-item>
                <el-form-item label="描述">
                  <el-input v-model="form.description" />
                </el-form-item>
                <el-form-item label="模型">
                  <el-select v-model="form.llm_model">
                    <el-option label="Qwen-Max" value="qwen-max" />
                    <el-option label="Qwen-Plus" value="qwen-plus" />
                  </el-select>
                </el-form-item>
                <el-form-item label="系统提示词">
                  <el-input type="textarea" v-model="form.system_prompt" :rows="4" />
                </el-form-item>
                <el-form-item label="开场白">
                  <el-input type="textarea" v-model="form.greeting_message" :rows="2" placeholder="聊天开始时展示的消息" />
                </el-form-item>
                <el-form-item label="温度">
                  <el-slider v-model="form.temperature" :min="0" :max="1" :step="0.1" show-input />
                </el-form-item>
            </el-tab-pane>
            
            <el-tab-pane label="记忆" name="memory">
                <el-form-item label="短期记忆">
                    <el-switch v-model="form.memory_config.enable_short_term" />
                </el-form-item>
                <el-form-item label="窗口大小" v-if="form.memory_config.enable_short_term">
                    <el-input-number v-model="form.memory_config.window_size" :min="1" :max="20" />
                </el-form-item>
                <el-form-item label="长期记忆">
                    <el-switch v-model="form.memory_config.enable_long_term" />
                </el-form-item>
            </el-tab-pane>
            
            <el-tab-pane label="RAG 与知识库" name="rag">
                <el-form-item label="知识库">
                  <el-select v-model="form.kb_ids" multiple placeholder="选择知识库">
                    <el-option
                      v-for="item in kbs"
                      :key="item.id"
                      :label="item.name"
                      :value="item.id"
                    />
                  </el-select>
                </el-form-item>
                
                <el-divider content-position="left">检索配置</el-divider>
                
                <el-form-item label="Top-K 召回">
                    <el-slider v-model="form.rag_config.top_k" :min="1" :max="20" show-input />
                </el-form-item>
                
                <el-form-item label="混合权重">
                    <el-tooltip content="待后续实现（0.0 - 1.0）" placement="top">
                        <el-slider v-model="form.rag_config.hybrid_weight" :min="0" :max="1" :step="0.1" show-input />
                    </el-tooltip>
                </el-form-item>
                
                <el-form-item label="启用重排">
                    <el-switch v-model="form.rag_config.enable_rerank" />
                </el-form-item>
                
                <el-form-item label="重排 Top-N" v-if="form.rag_config.enable_rerank">
                    <el-input-number v-model="form.rag_config.rerank_top_n" :min="1" :max="20" />
                </el-form-item>
            </el-tab-pane>
        </el-tabs>
      </el-form>
      <template #footer>
        <span class="dialog-footer">
          <el-button @click="dialogVisible = false">取消</el-button>
          <el-button type="primary" @click="saveAssistant">确定</el-button>
        </span>
      </template>
    </el-dialog>

    <!-- Full Screen Chat Interface -->
    <div v-if="chatVisible" class="full-screen-chat">
        <div class="chat-header">
            <div class="header-left">
                <el-button icon="Back" circle @click="chatVisible = false" style="margin-right: 10px;" />
                <h3>{{ currentChatAssistant?.name }}</h3>
                <el-tag v-if="currentVersion" type="info" style="margin-left: 10px;">{{ currentVersion }}</el-tag>
            </div>
            <div class="header-right">
                 <el-select v-model="chatModel" placeholder="模型" style="width: 150px; margin-right: 10px;">
                    <el-option label="Qwen-Max" value="qwen-max" />
                    <el-option label="Qwen-Plus" value="qwen-plus" />
                 </el-select>
                 <el-select v-model="currentVersion" placeholder="版本" style="width: 120px; margin-right: 10px;" @change="restoreVersion">
                    <el-option v-for="v in assistantVersions" :key="v.version" :label="v.version" :value="v.version" />
                 </el-select>
                 <el-button type="primary" @click="saveNewVersion">保存版本</el-button>
                 <el-button @click="startNewChat" type="success" plain style="margin-left: 10px;">新会话</el-button>
                 <el-button @click="clearHistory" type="danger" plain style="margin-left: 10px;">清空历史</el-button>
            </div>
        </div>
        
        <div class="chat-body">
            <!-- Left Panel: Assistant Info -->
            <div class="info-panel">
                <el-scrollbar>
                    <div style="padding: 20px;">
                        <h4>助手配置</h4>
                        <el-form :model="form" label-width="120px" label-position="top">
                            <el-tabs v-model="activeTab">
                                <el-tab-pane label="基本信息" name="basic">
                                    <el-form-item label="名称">
                                      <el-input v-model="form.name" />
                                    </el-form-item>
                                    <el-form-item label="描述">
                                      <el-input v-model="form.description" />
                                    </el-form-item>
                                    <el-form-item label="系统提示词">
                                      <el-input type="textarea" v-model="form.system_prompt" :rows="6" />
                                    </el-form-item>
                                    <el-form-item label="开场白">
                                      <el-input type="textarea" v-model="form.greeting_message" :rows="3" />
                                    </el-form-item>
                                    <el-form-item label="温度">
                                      <el-slider v-model="form.temperature" :min="0" :max="1" :step="0.1" show-input />
                                    </el-form-item>
                                </el-tab-pane>
                                
                                <el-tab-pane label="记忆" name="memory">
                                <el-form-item label="短期记忆">
                                    <el-switch v-model="form.memory_config.enable_short_term" />
                                </el-form-item>
                                <el-form-item label="窗口大小" v-if="form.memory_config.enable_short_term">
                                    <el-input-number v-model="form.memory_config.window_size" :min="1" :max="20" />
                                    <div class="form-tip">保留最近对话轮数（建议 5-10）</div>
                                </el-form-item>
                                <el-form-item label="长期记忆">
                                    <el-switch v-model="form.memory_config.enable_long_term" />
                                    <div class="form-tip">基于语义相似度从向量库中检索相关历史</div>
                                </el-form-item>
                            </el-tab-pane>
                            
                            <el-tab-pane label="RAG 与知识库" name="rag">
                                    <el-form-item label="知识库">
                                      <el-select v-model="form.kb_ids" multiple placeholder="选择知识库" style="width: 100%;">
                                        <el-option
                                          v-for="item in kbs"
                                          :key="item.id"
                                          :label="item.name"
                                          :value="item.id"
                                        />
                                      </el-select>
                                    </el-form-item>
                                    
                                    <el-divider content-position="left">检索配置</el-divider>
                                    
                                    <el-form-item label="Top-K 召回">
                                        <el-slider v-model="form.rag_config.top_k" :min="1" :max="20" show-input />
                                    </el-form-item>
                                    
                                    <el-form-item label="混合权重">
                                        <el-slider v-model="form.rag_config.hybrid_weight" :min="0" :max="1" :step="0.1" show-input />
                                    </el-form-item>
                                    
                                    <el-form-item label="启用重排">
                                        <el-switch v-model="form.rag_config.enable_rerank" />
                                    </el-form-item>
                                    
                                    <el-form-item label="重排 Top-N" v-if="form.rag_config.enable_rerank">
                                        <el-input-number v-model="form.rag_config.rerank_top_n" :min="1" :max="20" />
                                    </el-form-item>
                                </el-tab-pane>
                            </el-tabs>
                        </el-form>
                    </div>
                </el-scrollbar>
            </div>
            
            <!-- Right Panel: Chat Interface -->
            <div class="chat-panel">
                <div class="chat-greeting" v-if="form.greeting_message">
                    <el-alert :title="form.greeting_message" type="info" :closable="false" show-icon />
                </div>
                
                <div class="kb-info" v-if="chatLinkedKBs.length" style="padding: 10px 20px; border-bottom: 1px solid #eee;">
                    <span style="color: #666; font-size: 0.9em; margin-right: 10px;">关联知识库：</span>
                    <el-tag v-for="kb in chatLinkedKBs" :key="kb.id" size="small" style="margin-right: 5px;">{{ kb.name }}</el-tag>
                </div>
                
                <div class="messages" ref="messagesContainer">
                    <div v-for="(msg, index) in chatMessages" :key="index" :class="['message', msg.role]">
                      <div class="message-content markdown-body" v-html="renderMarkdown(msg.content)"></div>
                      <div v-if="msg.sources && msg.sources.length" class="sources">
                        <small>参考来源：</small>
                        <ul>
                          <li v-for="src in msg.sources" :key="src.id">
                            {{ src.text.substring(0, 50) }}...
                          </li>
                        </ul>
                      </div>
                    </div>
                    <div v-if="chatLoading" class="message assistant">
                        <div class="message-content">
                            <span class="typing-dot">.</span><span class="typing-dot">.</span><span class="typing-dot">.</span>
                        </div>
                    </div>
                </div>
                
                <div class="input-area">
                    <el-input 
                      v-model="inputQuery" 
                      placeholder="输入您的问题..." 
                      @keyup.enter="sendMessage"
                      :rows="3"
                      type="textarea"
                      resize="none"
                    >
                    </el-input>
                    <div style="text-align: right; margin-top: 10px;">
                        <el-button type="primary" @click="sendMessage" icon="Position">发送</el-button>
                    </div>
                </div>
            </div>
        </div>
    </div>


  </div>
</template>

<script setup>
import { ref, reactive, onMounted, nextTick, computed } from 'vue'
import { useRouter } from 'vue-router'
import api from '../api'
import { ElMessage } from 'element-plus'
import { Back, Position } from '@element-plus/icons-vue'
import { confirmAction } from '../utils/confirm'
import { renderMarkdown } from '../utils/chat'

const router = useRouter()
const assistants = ref([])
const kbs = ref([])
const agents = ref([])
const dialogVisible = ref(false)
const isEdit = ref(false)
const currentId = ref(null)
const activeTab = ref('basic')

// Chat Drawer State
const chatVisible = ref(false)
const currentChatAssistant = ref(null)
const chatMessages = ref([])
const inputQuery = ref('')
const currentSessionId = ref(null)
const messagesContainer = ref(null)
const chatModel = ref('qwen-max')
const currentVersion = ref('v1.0.0')
const assistantVersions = ref([])

const form = reactive({
  name: '',
  description: '',
  llm_model: 'qwen-max',
  temperature: 0.7,
  system_prompt: '',
  greeting_message: '',
  kb_ids: [],
  agent_ids: [],
  memory_config: {
      enable_short_term: true,
      window_size: 10,
      enable_long_term: false
  },
  rag_config: {
      top_k: 5,
      hybrid_weight: 0.5,
      enable_rerank: false,
      rerank_top_n: 5
  }
})

const fetchAssistants = async () => {
  const res = await api.get('/assistants/')
  assistants.value = res.data
}

const fetchKBs = async () => {
  const res = await api.get('/knowledge-bases/')
  kbs.value = res.data
}

const fetchAgents = async () => {
  const res = await api.get('/agents/')
  agents.value = res.data
}

const chatLinkedKBs = computed(() => {
    if (!currentChatAssistant.value || !currentChatAssistant.value.kb_ids) return []
    return kbs.value.filter(kb => currentChatAssistant.value.kb_ids.includes(kb.id))
})

const startChat = async (row) => {
    currentChatAssistant.value = row
    chatModel.value = row.llm_model
    chatMessages.value = []
    currentSessionId.value = null
    inputQuery.value = ''
    
    // Load History
    try {
        // Fetch all sessions first
        const res = await api.get('/chat/sessions')
        // Filter sessions for this assistant
        const sessions = res.data.filter(s => s.assistant_id === row.id)
        
        if (sessions.length > 0) {
            // Sort by created_at desc to get the latest session
            sessions.sort((a, b) => new Date(b.created_at) - new Date(a.created_at))
            const latest = sessions[0]
            currentSessionId.value = latest.session_uid
            
            // Fetch messages for this session
            const msgRes = await api.get(`/chat/sessions/${latest.session_uid}/messages`)
            console.log('Chat History Response:', msgRes.data)
            
            // Backend returns [{query:..., answer:..., created_at:...}]
            // We need to flatten this to chatMessages format: {role: 'user', content: ...}, {role: 'assistant', content: ...}
            const history = []
            if (Array.isArray(msgRes.data)) {
                msgRes.data.forEach(item => {
                    if (item.query) {
                        history.push({ role: 'user', content: item.query })
                    }
                    if (item.answer) {
                        history.push({ 
                            role: 'assistant', 
                            content: item.answer,
                            sources: item.source_documents || [] // Map sources if available
                        })
                    }
                })
            }
            chatMessages.value = history
            
            scrollToBottom()
        } else {
             // No history, create new session or wait for first message?
             // Usually we wait for first message to create session, OR create one now.
             // Let's create one now to ensure session ID exists
             const newSessionRes = await api.post('/chat/sessions', {
                 assistant_id: row.id
             })
             currentSessionId.value = newSessionRes.data.session_uid
             
             // Add greeting if exists
             if (row.greeting_message) {
                 // chatMessages.value.push({ role: 'assistant', content: row.greeting_message })
             }
        }
    } catch (e) {
        console.error("加载历史失败", e)
        ElMessage.error('加载会话历史失败')
    }
    
    // Fetch Versions
    await fetchVersions(row.id)
    if (assistantVersions.value.length > 0) {
        currentVersion.value = assistantVersions.value[assistantVersions.value.length - 1].version
    } else {
        currentVersion.value = 'v1.0.0'
    }

    // Populate form for Info Panel
    const data = JSON.parse(JSON.stringify(row))
    if (!data.rag_config) {
        data.rag_config = {
            top_k: 5,
            hybrid_weight: 0.5,
            enable_rerank: false,
            rerank_top_n: 5
        }
    }
    if (!data.memory_config) {
        data.memory_config = {
            enable_short_term: true,
            window_size: 10,
            enable_long_term: false
        }
    }
    Object.assign(form, data)
    
    chatVisible.value = true
}

const startNewChat = async () => {
    try {
        const res = await api.post('/chat/sessions', {
            assistant_id: currentChatAssistant.value.id
        })
        currentSessionId.value = res.data.session_uid
        chatMessages.value = []
        // Add greeting if exists
        if (currentChatAssistant.value.greeting_message) {
            // chatMessages.value.push({ role: 'assistant', content: currentChatAssistant.value.greeting_message })
        }
        ElMessage.success('新会话已开始')
    } catch (e) {
        ElMessage.error('开启新会话失败')
    }
}

const clearHistory = async () => {
    if (!currentSessionId.value) return
    if (!(await confirmAction('确定清空会话历史吗？', '警告'))) return
    try {
        await api.delete(`/chat/sessions/${currentSessionId.value}`)
        chatMessages.value = []
        currentSessionId.value = null
        ElMessage.success('历史已清空')
    } catch (e) {
        ElMessage.error('清空历史失败')
    }
}

const fetchVersions = async (id) => {
    try {
        const res = await api.get(`/assistants/${id}/versions`)
        assistantVersions.value = res.data
    } catch (e) {
        assistantVersions.value = []
    }
}

const saveNewVersion = async () => {
    if (!currentChatAssistant.value) return
    try {
        const nextVer = incrementVersion(currentVersion.value)
        
        // Use form state for the new config
        // Also update currentChatAssistant.value locally to reflect changes immediately
        const updatedConfig = {
            ...currentChatAssistant.value, // Keep ID, user_id etc
            name: form.name,
            description: form.description,
            system_prompt: form.system_prompt,
            greeting_message: form.greeting_message,
            temperature: form.temperature,
            memory_config: form.memory_config,
            rag_config: form.rag_config,
            kb_ids: form.kb_ids,
            llm_model: chatModel.value
        }
        
        // UPDATE ASSISTANT CONFIG FIRST
        await api.put(`/assistants/${currentChatAssistant.value.id}`, {
            name: form.name,
            description: form.description,
            system_prompt: form.system_prompt,
            greeting_message: form.greeting_message,
            temperature: form.temperature,
            memory_config: form.memory_config,
            rag_config: form.rag_config,
            kb_ids: form.kb_ids,
            llm_model: chatModel.value
        })

        await api.post(`/assistants/${currentChatAssistant.value.id}/versions`, {
            version: nextVer,
            config: updatedConfig
        })
        
        ElMessage.success(`已保存版本 ${nextVer} 并更新助手`)
        currentVersion.value = nextVer
        fetchVersions(currentChatAssistant.value.id)
        // Refresh main list
        fetchAssistants()
    } catch (e) {
        ElMessage.error('保存版本失败')
    }
}

const incrementVersion = (ver) => {
    if (!ver) return 'v1.0.0'
    // Format vX.Y.Z
    const parts = ver.replace('v', '').split('.').map(Number)
    if (parts.length !== 3) return 'v1.0.0'
    
    let [major, minor, patch] = parts
    
    patch += 1
    if (patch >= 10) {
        patch = 0
        minor += 1
    }
    if (minor >= 10) {
        minor = 0
        major += 1
    }
    
    return `v${major}.${minor}.${patch}`
}

const restoreVersion = async (verStr) => {
    // Find version config
    const verObj = assistantVersions.value.find(v => v.version === verStr)
    if (!verObj || !verObj.config) return
    if (!(await confirmAction(`确定恢复到 ${verStr} 吗？`))) return
    try {
        await api.put(`/assistants/${currentChatAssistant.value.id}`, verObj.config)
        ElMessage.success('已恢复')
        // Update local state
        chatModel.value = verObj.config.llm_model
        fetchAssistants() // Refresh table
    } catch (e) {
        ElMessage.error('恢复失败')
    }
}

const chatLoading = ref(false)

const sendMessage = async () => {
  if (!inputQuery.value.trim() || chatLoading.value) return
  
  const query = inputQuery.value
  chatMessages.value.push({ role: 'user', content: query })
  inputQuery.value = ''
  chatLoading.value = true
  scrollToBottom()
  
  try {
    const payload = {
      query: query,
      session_id: currentSessionId.value,
      assistant_id: currentChatAssistant.value.id
    }
    
    const res = await api.post('/chat/', payload)
    
    currentSessionId.value = res.data.session_id
    chatMessages.value.push({ 
      role: 'assistant', 
      content: res.data.answer,
      sources: res.data.source_documents
    })
    scrollToBottom()
  } catch (e) {
    console.error(e)
    chatMessages.value.push({ role: 'system', content: '发送消息失败：' + (e.response?.data?.detail || e.message) })
    scrollToBottom()
  } finally {
    chatLoading.value = false
  }
}

const scrollToBottom = () => {
  nextTick(() => {
    if (messagesContainer.value) {
      messagesContainer.value.scrollTop = messagesContainer.value.scrollHeight
    }
  })
}

const openDialog = (row = null) => {
  activeTab.value = 'basic'
  if (row) {
    isEdit.value = true
    currentId.value = row.id
    // Deep copy to avoid reference issues, and handle missing rag_config
    const data = JSON.parse(JSON.stringify(row))
    if (!data.rag_config) {
        data.rag_config = {
            top_k: 5,
            hybrid_weight: 0.5,
            enable_rerank: false,
            rerank_top_n: 5
        }
    }
    Object.assign(form, data)
  } else {
    isEdit.value = false
    currentId.value = null
    Object.assign(form, {
      name: '',
      description: '',
      llm_model: 'qwen-max',
      temperature: 0.7,
      system_prompt: '',
      greeting_message: '',
      kb_ids: [],
      agent_ids: [],
      rag_config: {
          top_k: 5,
          hybrid_weight: 0.5,
          enable_rerank: false,
          rerank_top_n: 5
      }
    })
  }
  dialogVisible.value = true
}

const saveAssistant = async () => {
  try {
    if (isEdit.value) {
      await api.put(`/assistants/${currentId.value}`, form)
    } else {
      await api.post('/assistants/', form)
    }
    dialogVisible.value = false
    fetchAssistants()
    ElMessage.success('助手保存成功')
  } catch (e) {
    console.error(e)
    ElMessage.error('操作失败')
  }
}

const deleteAssistant = async (id) => {
  if (!(await confirmAction('确定删除吗？'))) return
  try {
    await api.delete(`/assistants/${id}`)
    fetchAssistants()
    ElMessage.success('助手删除成功')
  } catch (e) {
    ElMessage.error('删除失败')
  }
}

onMounted(() => {
  fetchAssistants()
  fetchKBs()
  fetchAgents()
})
</script>

<style scoped>
.full-screen-chat {
    position: fixed;
    top: 0;
    left: 0;
    width: 100vw;
    height: 100vh;
    background: white;
    z-index: 2000;
    display: flex;
    flex-direction: column;
}

.chat-header {
    height: 60px;
    border-bottom: 1px solid #dcdfe6;
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 0 20px;
    background: #f5f7fa;
}

.header-left, .header-right {
    display: flex;
    align-items: center;
}

.chat-body {
    flex: 1;
    display: flex;
    overflow: hidden;
}

.info-panel {
    width: 40%;
    border-right: 1px solid #dcdfe6;
    background: #fff;
    display: flex;
    flex-direction: column;
}

.chat-panel {
    width: 60%;
    display: flex;
    flex-direction: column;
    background: #fafafa;
}

.chat-greeting {
    padding: 10px 20px;
}

.messages {
    flex: 1;
    overflow-y: auto;
    padding: 20px;
}

.message {
    margin-bottom: 20px;
    max-width: 80%;
}

.message.user {
    margin-left: auto;
    background-color: #ecf5ff;
    padding: 15px;
    border-radius: 12px;
    border-bottom-right-radius: 2px;
}

.message.assistant {
    margin-right: auto;
    background-color: #fff;
    padding: 15px;
    border-radius: 12px;
    border-bottom-left-radius: 2px;
    box-shadow: 0 2px 4px rgba(0,0,0,0.05);
}

.input-area {
    padding: 20px;
    background: #fff;
    border-top: 1px solid #eee;
}

.sources {
    margin-top: 10px;
    font-size: 0.85em;
    color: #909399;
    border-top: 1px dashed #eee;
    padding-top: 5px;
    display: none; /* Hide by default */
}

.message:hover .sources {
    display: block; /* Show on hover */
    animation: fadeIn 0.3s;
}

@keyframes fadeIn {
    from { opacity: 0; }
    to { opacity: 1; }
}

.typing-dot {
    animation: typing 1.4s infinite ease-in-out both;
    margin: 0 2px;
    font-weight: bold;
    font-size: 1.2em;
}

.typing-dot:nth-child(1) { animation-delay: -0.32s; }
.typing-dot:nth-child(2) { animation-delay: -0.16s; }

@keyframes typing {
    0%, 80%, 100% { opacity: 0; }
    40% { opacity: 1; }
}
/* Markdown 渲染样式 */
.markdown-body :deep(h1),
.markdown-body :deep(h2),
.markdown-body :deep(h3),
.markdown-body :deep(h4) {
    margin-top: 0.6em;
    margin-bottom: 0.3em;
    font-weight: 600;
}
.markdown-body :deep(p) {
    margin: 0.4em 0;
}
.markdown-body :deep(ul),
.markdown-body :deep(ol) {
    padding-left: 1.5em;
    margin: 0.4em 0;
}
.markdown-body :deep(code) {
    background-color: #f0f0f0;
    padding: 0.15em 0.4em;
    border-radius: 3px;
    font-size: 0.9em;
}
.markdown-body :deep(pre) {
    background-color: #f5f5f5;
    padding: 0.8em;
    border-radius: 6px;
    overflow-x: auto;
    margin: 0.5em 0;
}
.markdown-body :deep(pre code) {
    background: none;
    padding: 0;
}
.markdown-body :deep(strong) {
    font-weight: 700;
}
.markdown-body :deep(blockquote) {
    border-left: 3px solid #ddd;
    padding-left: 0.8em;
    color: #666;
    margin: 0.5em 0;
}
.markdown-body :deep(table) {
    border-collapse: collapse;
    margin: 0.5em 0;
    width: 100%;
}
.markdown-body :deep(th),
.markdown-body :deep(td) {
    border: 1px solid #ddd;
    padding: 0.4em 0.6em;
    text-align: left;
}
.markdown-body :deep(th) {
    background-color: #f5f5f5;
    font-weight: 600;
}
</style>
