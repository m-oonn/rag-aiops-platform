<script setup>
import { onUnmounted, ref, watch } from "vue";
import { request } from "../lib/api";
import { useLoad, dateTime, docStatus, tone, runStatus } from "../lib/ui";
import { getHistory, rememberRun, mergeHistoryList, markHistoryRunUnavailable } from "../lib/history";
import { session } from "../lib/session";
import PageHeader from "../components/PageHeader.vue";
import Feedback from "../components/Feedback.vue";
import Icon from "../components/Icon.vue";
const kbs = ref([]),
  assistants = ref([]),
  tasks = ref([]),
  stats = ref({}),
  dependencies = ref({}),
  partialError = ref("");
const available = ref([]);
const recent = ref(getHistory(session.user?.id).slice(0, 4)), recentLoading = ref(false);
const recentError = ref("");
let recentVersion = 0;
async function loadRecent() {
  const version = ++recentVersion, userId = session.user?.id;
  let saved;
  recentError.value = "";
  try {
    const result = await request("/aiops/runs", { query: { limit: 100 } });
    if (version !== recentVersion || userId !== session.user?.id) return;
    saved = mergeHistoryList(getHistory(userId), result.runs, userId, 4);
    saved.forEach(row => rememberRun(userId, row));
  } catch (e) {
    if (version !== recentVersion || userId !== session.user?.id) return;
    recentError.value = `服务器历史暂不可读取，显示此浏览器已保存的记录：${e.message}`;
    saved = getHistory(userId).slice(0, 4);
  }
  recent.value = saved;
  recentLoading.value = true;
  const results = await Promise.allSettled(saved.map(row => request(`/aiops/runs/${encodeURIComponent(row.thread_id)}`)));
  if (version !== recentVersion || userId !== session.user?.id) return;
  recent.value = mergeHistoryList(results.map((result, index) => {
    if (result.status === "rejected") return markHistoryRunUnavailable(saved[index], result.reason);
    const row = {...saved[index], ...result.value, readError: ""};
    rememberRun(userId, row);
    return row;
  }), null, userId, 4);
  recentLoading.value = false;
}
watch(() => session.user?.id, () => {
  recent.value = [];
  loadRecent();
});
onUnmounted(() => { recentVersion++; });
const { loading, error, refresh } = useLoad(async () => {
  const recentRead = loadRecent();
  const paths = [
    "/knowledge-bases/",
    "/assistants/",
    "/monitor/",
    "/monitor/stats",
    "/health/dependencies",
  ];
  const results = await Promise.allSettled(paths.map((path) => request(path)));
  await recentRead;
  available.value = results.map((row) => row.status === "fulfilled");
  const targets = [kbs, assistants, tasks, stats, dependencies];
  results.forEach((result, i) => {
    if (result.status === "fulfilled") targets[i].value = result.value;
  });
  const failures = results.filter((row) => row.status === "rejected");
  partialError.value = failures.length ? failures[0].reason.message : "";
  if (failures.length === results.length) throw failures[0].reason;
});
</script>
<template>
  <div class="page">
    <PageHeader title="工作台"
      ><button class="button" :disabled="loading" @click="refresh()">
        <Icon name="refresh" :size="16" />刷新</button
      ><RouterLink to="/aiops?new=1" class="button primary"
        ><Icon name="plus" :size="18" />新建诊断</RouterLink
      ></PageHeader
    ><Feedback :loading="loading" :error="error" @retry="refresh()" /><template
      v-if="!error || recent.length || recentLoading"
      ><div v-if="partialError" class="inline-feedback" role="alert">
        部分数据未能读取：{{ partialError }}
      </div>
      <div class="metric-strip">
        <RouterLink to="/knowledge-bases"
          ><span>知识库</span
          ><strong>{{ loading || !available[0] ? "—" : kbs.length }}</strong
          ><span class="metric-link"
            >管理知识 <Icon name="arrow" :size="16" /></span></RouterLink
        ><RouterLink to="/chat"
          ><span>可用助手</span
          ><strong>{{
            loading || !available[1] ? "—" : assistants.length
          }}</strong
          ><span class="metric-link"
            >进入问答 <Icon name="arrow" :size="16" /></span></RouterLink
        ><RouterLink to="/monitor"
          ><span>处理中</span
          ><strong>{{ stats.total_processing ?? "—" }}</strong
          ><span class="metric-link"
            >查看进度 <Icon name="arrow" :size="16" /></span></RouterLink
        ><RouterLink to="/monitor?status=FAILURE"
          ><span>失败任务</span
          ><strong :class="{ 'text-danger': stats.total_failed > 0 }">{{
            stats.total_failed ?? "—"
          }}</strong
          ><span class="metric-link"
            >处理任务 <Icon name="arrow" :size="16" /></span
        ></RouterLink>
      </div>
      <div class="split-sections">
        <section>
          <div class="section-heading">
            <h2>最近诊断</h2>
            <button class="text-button" :disabled="recentLoading" @click="loadRecent">重新读取诊断</button>
            <RouterLink to="/aiops/history" class="text-button"
              >查看全部 <Icon name="arrow" :size="16"
            /></RouterLink>
          </div>
          <div v-if="recentError" class="inline-feedback" role="alert">{{ recentError }}</div>
          <div v-if="!recent.length && !recentError" class="empty-state compact">
            <span>暂无诊断记录</span
            ><RouterLink to="/aiops" class="text-button">开始诊断 →</RouterLink>
          </div>
          <RouterLink
            v-for="run in recent"
            :key="run.thread_id"
            :to="{ path: '/aiops', query: { run: run.thread_id } }"
            class="record-row"
            ><Icon name="pulse" />
            <div class="grow">
              <strong>{{ run.query || run.thread_id }}</strong
              ><span class="muted">{{ dateTime(run.updated_at) }}</span>
            </div>
            <span v-if="recentLoading" class="muted">状态核实中</span>
            <span v-else-if="run.readError" class="text-danger" role="alert">状态未核实：{{ run.readError }}</span>
            <span v-else :class="['status', tone(run.status)]">{{
              runStatus(run.status)
            }}</span
            ><Icon name="chevron" :size="16"
          /></RouterLink>
        </section>
        <section>
          <div class="section-heading">
            <h2>服务状态</h2>
            <RouterLink to="/platform" class="text-button"
              >查看全部 <Icon name="arrow" :size="16"
            /></RouterLink>
          </div>
          <div
            v-if="!Object.keys(dependencies.services || {}).length"
            class="empty-state compact"
          >
            暂无服务状态
          </div>
          <div
            v-for="(service, name) in dependencies.services"
            :key="name"
            class="service-line"
          >
            <span>{{
              {
                llm: "语言模型",
                milvus: "向量检索",
                minio: "文件存储",
                redis: "缓存",
                rabbitmq: "消息队列",
                probe: "主机采集",
                mcp_monitor: "指标服务",
                mcp_cls: "日志服务",
              }[name] || name
            }}</span
            ><span :class="['status', tone(service.status)]">{{
              service.status === "ok"
                ? "可用"
                : service.status === "disabled"
                  ? "未启用"
                  : "不可用"
            }}</span>
          </div>
        </section>
      </div>
      <section class="section">
        <div class="section-heading">
          <h2>文档处理</h2>
          <RouterLink to="/monitor" class="text-button"
            >全部任务 <Icon name="arrow" :size="16"
          /></RouterLink>
        </div>
        <div v-if="!tasks.length" class="empty-state compact">暂无文档任务</div>
        <div
          v-for="task in tasks.slice(0, 5)"
          :key="task.doc_id"
          class="record-row"
        >
          <Icon name="file" />
          <div class="grow">
            <strong>{{ task.filename }}</strong
            ><span class="muted">{{ task.kb_name }}</span>
          </div>
          <span :class="['status', tone(task.status)]">{{
            docStatus(task.status)
          }}</span
          ><time class="muted">{{ dateTime(task.created_at) }}</time>
        </div>
      </section></template
    >
  </div>
</template>
