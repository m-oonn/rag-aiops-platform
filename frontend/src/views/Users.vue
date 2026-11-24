<script setup>
import { computed, ref } from "vue";
import { request } from "../lib/api";
import { fail, notify, useLoad } from "../lib/ui";
import { session } from "../lib/session";
import PageHeader from "../components/PageHeader.vue";
import Feedback from "../components/Feedback.vue";
import DataTable from "../components/DataTable.vue";
import Modal from "../components/Modal.vue";
import InsightBreakdown from "../components/InsightBreakdown.vue";
import { breakdown } from "../lib/breakdown";
import Icon from "../components/Icon.vue";
const rows = ref([]),
  search = ref(""),
  createOpen = ref(false),
  busy = ref(false),
  form = ref({ username: "", email: "", password: "" }),
  errorText = ref("");
const roleFilter = ref('');
const roles = { user: '成员', auditor: '审计员', admin: '管理员' };
const roleOf = row => row.role || 'user';
const roleChart = computed(() => breakdown(rows.value, roleOf, key => roles[key] || key,
  key => key === 'admin' ? 'warning' : key === 'auditor' ? 'success' : 'info'));
const visible = computed(() =>
  rows.value.filter((row) =>
    (!roleFilter.value || roleOf(row) === roleFilter.value) && `${row.username} ${row.email}`
      .toLowerCase()
      .includes(search.value.toLowerCase()),
  ),
);
const { loading, error, refresh } = useLoad(async () => {
  rows.value = await request("/auth/users");
});
async function role(row, value) {
  try {
    await request(`/auth/users/${row.id}/role`, {
      method: "PATCH",
      body: { role: value },
    });
    row.role = value;
    notify("角色已更新");
  } catch (e) {
    fail(e);
    await refresh();
  }
}
async function create() {
  busy.value = true;
  errorText.value = "";
  try {
    await request("/auth/register", { method: "POST", body: form.value });
    createOpen.value = false;
    form.value = { username: "", email: "", password: "" };
    await refresh();
    notify("用户已创建");
  } catch (e) {
    errorText.value = e.message;
  } finally {
    busy.value = false;
  }
}
</script>
<template>
  <div class="page">
    <PageHeader title="用户管理"
      ><button class="button" :disabled="loading" @click="refresh()">
        <Icon name="refresh" :size="16" />刷新</button
      ><button class="button primary" @click="createOpen = true">
        <Icon name="plus" :size="16" />新建用户
      </button></PageHeader
    >
    <InsightBreakdown v-if="!error" v-model="roleFilter" :items="roleChart" title="账号角色分布" icon="users"
      description="含已停用账号；点击角色查看对应人员，不会修改权限。" variant="composition" unit="人" />
    <div class="toolbar">
      <label class="search-input"
        ><Icon name="search" /><input
          v-model="search"
          placeholder="搜索用户名或邮箱"
          aria-label="搜索用户" /></label
      ><span class="muted">{{ visible.length }} 个用户</span>
    </div>
    <Feedback
      :loading="loading"
      :error="error"
      :empty="!visible.length && !loading"
      text="暂无用户"
      @retry="refresh()"
    /><DataTable
      v-if="visible.length"
      :rows="visible"
      :columns="[
        { key: 'username', label: '用户名', width: '28%' },
        { key: 'email', label: '邮箱', width: '35%' },
        { key: 'role', label: '角色' },
        { key: 'is_active', label: '状态' },
      ]"
      ><template #username="{ row }"
        ><div class="cell-title">
          <span class="avatar">{{
            row.username.slice(0, 1).toUpperCase()
          }}</span
          ><strong>{{ row.username }}</strong
          ><span v-if="row.id === session.user?.id" class="tag">当前账号</span>
        </div></template
      ><template #email="{ row }">{{ row.email }}</template
      ><template #role="{ row }"
        ><select
          :value="row.role || 'user'"
          :disabled="row.id === session.user?.id"
          :aria-label="`${row.username}角色`"
          class="filter-select"
          @change="role(row, $event.target.value)"
        >
          <option value="user">成员</option>
          <option value="auditor">审计员</option>
          <option value="admin">管理员</option>
        </select></template
      ><template #is_active="{ row }"
        ><span :class="['status', row.is_active ? 'success' : 'muted']">{{
          row.is_active ? "正常" : "已停用"
        }}</span></template
      ></DataTable
    ><Modal v-model="createOpen" title="新建用户"
      ><form @submit.prevent="create">
        <label class="field"
          >用户名<input
            v-model.trim="form.username"
            autocomplete="username"
            required
            maxlength="120" /></label
        ><label class="field"
          >邮箱<input
            v-model.trim="form.email"
            type="email"
            autocomplete="email"
            required /></label
        ><label class="field"
          >初始密码<input
            v-model="form.password"
            type="password"
            autocomplete="new-password"
            minlength="6"
            required
        /></label>
        <p v-if="errorText" role="alert" class="field-error">{{ errorText }}</p>
        <div class="form-actions">
          <button type="button" class="button" @click="createOpen = false">
            取消</button
          ><button class="button primary" :disabled="busy">创建账号</button>
        </div>
      </form></Modal
    >
  </div>
</template>
