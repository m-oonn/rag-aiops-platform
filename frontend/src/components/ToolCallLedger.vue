<script setup>
defineProps({ calls: { type: Array, default: () => [] }, error: String });
defineEmits(["retry"]);
const statusName = value => ({ success: "成功", blocked: "被拒绝", failed: "失败", unavailable: "不可用",
  running: "执行中", pending: "执行中", cancelled: "已取消", fallback: "已换路", pending_approval: "等待审批" }[value] || value);
</script>

<template>
  <section aria-label="逐次工具调用" class="tool-ledger">
    <h3>逐次工具调用 <span v-if="!error">{{ calls.length }}</span></h3>
    <div v-if="error" role="alert">{{ error }} <button class="text-button" @click="$emit('retry')">重读工具记录</button></div>
    <p v-else-if="!calls.length">本轮尚无调用记录。</p>
    <details v-for="call in calls" :key="call.call_id">
      <summary>{{ call.step || '准备排查' }} · {{ call.tool }} · {{ statusName(call.status) }}
        <span v-if="call.elapsed_ms != null"> · {{ call.elapsed_ms }} ms</span></summary>
      <p v-if="call.reason">原因：{{ call.reason }}</p>
      <p>开始：{{ call.started_at || '未记录' }} · 结束：{{ call.completed_at || '未结束' }}</p>
      <h4>提议与实际参数（已脱敏）</h4><pre>{{ JSON.stringify(call.arguments, null, 2) }}</pre>
      <h4>返回结果（已脱敏）</h4><pre>{{ call.result || '未记录结果' }}</pre>
      <p v-if="call.result_truncated" role="note">结果已截断；完整原文是否可读，以本轮证据记录为准。</p>
      <small>调用编号：{{ call.call_id }} · 步骤：{{ call.step_index ?? '未记录' }}</small>
    </details>
  </section>
</template>

<style scoped>
.tool-ledger { margin-top: 24px; border-top: 1px solid var(--line); padding-top: 16px; }
.tool-ledger details { border-bottom: 1px solid var(--line); padding: 12px 0; }
.tool-ledger summary { cursor: pointer; overflow-wrap: anywhere; }
.tool-ledger pre { max-height: 360px; overflow: auto; white-space: pre-wrap; overflow-wrap: anywhere; }
.tool-ledger small, .tool-ledger p { color: var(--muted); }
</style>
