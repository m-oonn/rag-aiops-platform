<script setup>
import { computed, nextTick, reactive, ref, watch } from "vue";
import { request } from "../lib/api";
import { confirmAction, fail, useLoad, dateTime } from "../lib/ui";
import { session } from "../lib/session";
import PageHeader from "../components/PageHeader.vue";
import Feedback from "../components/Feedback.vue";
import Markdown from "../components/Markdown.vue";
import Icon from "../components/Icon.vue";
const sessions = ref([]),
  assistants = ref([]),
  knowledgeBases = ref([]),
  models = ref([]),
  selectedId = ref(""),
  messages = ref([]),
  busy = ref(false),
  draft = ref(""),
  error = ref(""),
  scrollBox = ref(null),
  sidebar = ref(false);
const form = reactive({ assistant_id: "", kb_id: "", llm_model: "", top_k: 5 });
const current = computed(() =>
  sessions.value.find((row) => row.session_uid === selectedId.value),
);
const title = computed(
  () =>
    current.value?.title || messages.value[0]?.query?.slice(0, 50) || "新会话",
);
async function load() {
  const result = await Promise.allSettled([
    request("/chat/sessions"),
    request("/assistants/"),
    request("/knowledge-bases/"),
    request("/health/models"),
  ]);
  if (result[0].status === "fulfilled") sessions.value = result[0].value;
  else throw result[0].reason;
  assistants.value = result[1].status === "fulfilled" ? result[1].value : [];
  knowledgeBases.value =
    result[2].status === "fulfilled" ? result[2].value : [];
  if (result[3].status === "fulfilled")
    models.value = result[3].value.models || [];
  if (!form.llm_model && result[3].status === "fulfilled")
    form.llm_model = result[3].value.default_model || "";
}
const { loading, error: loadError, refresh } = useLoad(load);
async function select(id) {
  if (busy.value) return;
  selectedId.value = id;
  sidebar.value = false;
  form.assistant_id =
    sessions.value.find((row) => row.session_uid === id)?.assistant_id || "";
  messages.value = [];
  if (!id) return;
  try {
    const history = await request(
      `/chat/sessions/${encodeURIComponent(id)}/messages`,
    );
    if (selectedId.value === id) messages.value = history;
  } catch (e) {
    if (selectedId.value === id) fail(e);
  }
  await scrollBottom();
}
async function newChat() {
  if (busy.value) return;
  try {
    const created = await request("/chat/sessions", {
      method: "POST",
      body: {
        assistant_id: form.assistant_id ? Number(form.assistant_id) : null,
      },
    });
    draft.value = "";
    messages.value = [];
    sessions.value.unshift(created);
    selectedId.value = created.session_uid;
    await nextTick();
    document.querySelector("#chat-draft")?.focus();
    sidebar.value = false;
  } catch (e) {
    fail(e);
  }
}
async function send() {
  const content = draft.value.trim();
  if (!content || busy.value) return;
  error.value = "";
  draft.value = "";
  messages.value.push({ query: content, answer: "", pending: true });
  const index = messages.value.length - 1;
  busy.value = true;
  await scrollBottom();
  try {
    const response = await request("/chat/", {
      method: "POST",
      body: {
        query: content,
        session_id: selectedId.value || null,
        assistant_id: form.assistant_id ? Number(form.assistant_id) : null,
        kb_id: form.kb_id ? Number(form.kb_id) : null,
        llm_model: form.llm_model || null,
        top_k: Number(form.top_k),
      },
    });
    messages.value[index] = {
      query: content,
      answer: response.answer,
      source_documents: response.source_documents || [],
    };
    selectedId.value = response.session_id;
    sessions.value = await request("/chat/sessions");
  } catch (e) {
    messages.value.splice(index, 1);
    error.value = e.message;
    draft.value = content;
  } finally {
    busy.value = false;
    await scrollBottom();
    if (!error.value)
      await nextTick(() => document.querySelector("#chat-draft")?.focus());
  }
}
async function scrollBottom() {
  await nextTick();
  const el = scrollBox.value;
  if (el) el.scrollTop = el.scrollHeight;
}
async function remove(id) {
  if (
    busy.value ||
    !(await confirmAction("删除会话", "删除这段会话及其消息？", "删除", true))
  )
    return;
  try {
    await request(`/chat/sessions/${encodeURIComponent(id)}`, {
      method: "DELETE",
    });
    sessions.value = sessions.value.filter((s) => s.session_uid !== id);
    if (selectedId.value === id) {
      selectedId.value = "";
      messages.value = [];
    }
  } catch (e) {
    fail(e);
  }
}
watch(() => messages.value.length, scrollBottom);
</script>
<template>
  <div class="chat-page">
    <div class="page chat-toolbar">
      <PageHeader title="知识问答"
        ><button class="button primary" :disabled="busy" @click="newChat">
          <Icon name="plus" :size="16" />新建会话
        </button></PageHeader
      >
    </div>
    <Feedback v-if="loadError" :error="loadError" @retry="refresh()" />
    <div v-else class="chat-layout">
      <button
        v-if="sidebar"
        class="session-backdrop"
        aria-label="关闭会话列表"
        @click="sidebar = false"
      />
      <aside :class="['chat-sessions', { open: sidebar }]">
        <button class="text-button mobile-sessions" @click="sidebar = false">
          关闭会话列表
        </button>
        <div class="session-list">
          <div
            v-for="item in sessions"
            :key="item.session_uid"
            :class="[
              'session-row',
              { active: item.session_uid === selectedId },
            ]"
          >
            <button
              :aria-current="
                item.session_uid === selectedId ? 'page' : undefined
              "
              @click="select(item.session_uid)"
            >
              <strong>{{ item.title || "新会话" }}</strong
              ><span>{{ dateTime(item.created_at) }}</span></button
            ><button
              class="icon-button"
              :aria-label="`删除 ${item.title || '新会话'}`"
              @click="remove(item.session_uid)"
            >
              <Icon name="close" :size="15" />
            </button>
          </div>
          <div v-if="!sessions.length" class="empty-state compact">
            暂无会话
          </div>
        </div>
      </aside>
      <main class="chat-main">
        <header class="chat-header">
          <div class="actions">
            <button
              class="icon-button mobile-sessions"
              :aria-label="sidebar ? '收起会话列表' : '打开会话列表'"
              @click="sidebar = !sidebar"
            >
              <Icon name="menu" />
            </button>
            <div>
              <h2 class="truncate">{{ title }}</h2>
              <span v-if="current" class="muted">{{
                dateTime(current.created_at)
              }}</span>
            </div>
          </div>
          <select
            v-model="form.assistant_id"
            :disabled="busy"
            aria-label="选择助手"
          >
            <option value="">默认助手</option>
            <option
              v-for="assistant in assistants"
              :key="assistant.id"
              :value="assistant.id"
            >
              {{ assistant.name }}
            </option>
          </select>
        </header>
        <section ref="scrollBox" class="chat-messages" aria-live="polite">
          <div v-if="!messages.length" class="chat-welcome">
            <Icon class="icon" name="spark" :size="32" />
            <h2>
              {{
                assistants.find((a) => a.id === Number(form.assistant_id))
                  ?.greeting_message || "你好，需要查找什么？"
              }}
            </h2>
            <div class="suggestion-list">
              <button
                v-for="suggestion in [
                  '总结这份知识库的核心内容',
                  '查找相关的技术说明',
                  '对比两个概念的区别',
                ]"
                :key="suggestion"
                @click="
                  draft = suggestion;
                  $nextTick(() =>
                    document.querySelector('#chat-draft')?.focus(),
                  );
                "
              >
                {{ suggestion }}<Icon name="arrow" :size="16" />
              </button>
            </div>
          </div>
          <article
            v-for="(message, i) in messages"
            :key="i"
            class="chat-message"
          >
            <div class="message-label">
              <span class="avatar">{{
                session.user?.username?.slice(0, 1)
              }}</span
              ><span>{{ session.user?.username }}</span>
            </div>
            <div class="message-content">{{ message.query }}</div>
            <div class="message-label assistant-label">
              <Icon name="spark" :size="15" />{{
                assistants.find((a) => a.id === Number(form.assistant_id))
                  ?.name || "助手"
              }}
            </div>
            <div v-if="message.pending" class="feedback">
              <span class="spinner" />正在生成回答
            </div>
            <Markdown v-else :content="message.answer" />
            <details
              v-if="message.source_documents?.length"
              class="sources-disclosure"
            >
              <summary>
                参考资料 · {{ message.source_documents.length }}
              </summary>
              <div
                v-for="(source, j) in message.source_documents"
                :key="j"
                class="detail-line"
              >
                <strong>{{
                  source.metadata?.filename ||
                  source.filename ||
                  source.name ||
                  `资料 ${j + 1}`
                }}</strong>
                <p>
                  {{ source.content || source.text || source.page_content }}
                </p>
              </div>
            </details>
          </article>
          <div v-if="error" class="inline-feedback" role="alert">
            {{ error }}
          </div>
        </section>
        <form class="chat-composer" @submit.prevent="send">
          <div class="composer-options">
            <label
              >知识库<select
                v-model="form.kb_id"
                :disabled="busy"
                aria-label="选择知识库"
              >
                <option value="">使用助手设置</option>
                <option
                  v-for="kb in knowledgeBases"
                  :key="kb.id"
                  :value="kb.id"
                >
                  {{ kb.name }}
                </option>
              </select></label
            ><label
              >模型<select
                v-model="form.llm_model"
                :disabled="busy"
                aria-label="选择模型"
              >
                <option value="">默认模型</option>
                <option
                  v-for="model in models"
                  :key="model.id"
                  :value="model.id"
                >
                  {{ model.name }}
                </option>
              </select></label
            ><label
              >检索数量<input
                v-model.number="form.top_k"
                type="number"
                min="1"
                max="50"
                required
                :disabled="busy"
                aria-label="检索数量"
            /></label>
          </div>
          <div class="composer-box">
            <textarea
              id="chat-draft"
              v-model="draft"
              placeholder="输入问题…"
              rows="2"
              :disabled="busy"
              maxlength="12000"
              aria-label="输入问题"
              @keydown.ctrl.enter.prevent="send"
            /><button class="button primary" :disabled="busy || !draft.trim()">
              <span v-if="busy" class="spinner" /><Icon
                v-else
                name="send"
                :size="17"
              /><span class="send-label">发送</span>
            </button>
          </div>
        </form>
      </main>
    </div>
  </div>
</template>
