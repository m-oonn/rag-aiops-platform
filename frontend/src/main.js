import { createApp } from 'vue'
import './styles/tokens.css'
import './styles/base.css'
import { ElLoading } from 'element-plus'
// Element Plus 按需引入：模板组件与样式由 unplugin 自动注入；
// 以下三类需要显式引入样式——JS API（ElMessage/ElMessageBox）与 v-loading 指令。
import 'element-plus/es/components/message/style/css'
import 'element-plus/es/components/message-box/style/css'
import 'element-plus/es/components/loading/style/css'
import App from './App.vue'
import router from './router'
import { createPinia } from 'pinia'

const app = createApp(App)

app.use(createPinia())
app.use(router)
app.use(ElLoading)
app.mount('#app')
