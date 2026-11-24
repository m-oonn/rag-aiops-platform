<script setup>
import { computed, ref, watch, onMounted, onUnmounted } from "vue";
import { useRoute, useRouter } from "vue-router";
import { navigation } from "./router";
import { session } from "./lib/session";
import Icon from "./components/Icon.vue";
const route = useRoute(),
  router = useRouter(),
  mobileNav = ref(false);
const groups = computed(() =>
  navigation.map((group) => ({
    ...group,
    items: group.items.filter(
      (item) => !item.admin || session.user?.role === "admin",
    ),
  })),
);
const active = (path) =>
  path === "/aiops" ? route.path === path : route.path.startsWith(path);
watch(
  () => route.fullPath,
  () => {
    mobileNav.value = false;
  },
);
function logout() {
  session.logout();
  router.replace("/login");
}
function expired() {
  session.user = null;
  router.replace({ path: "/login", query: { redirect: route.fullPath } });
}
onMounted(() => window.addEventListener("session-expired", expired));
onUnmounted(() => window.removeEventListener("session-expired", expired));
</script>
<template>
  <RouterView v-if="route.meta.public" />
  <div v-else class="app-shell">
    <a class="skip-link" href="#main">跳至主内容</a>
    <aside class="sidebar">
      <RouterLink to="/dashboard" class="brand"
        ><span class="brand-symbol"><Icon name="pulse" :size="23" /></span
        ><span
          >AIOps<span class="brand-caption">运维工作空间</span></span
        ></RouterLink
      >
      <nav aria-label="主导航">
        <div v-for="group in groups" :key="group.label" class="nav-group">
          <div class="nav-label">{{ group.label }}</div>
          <RouterLink
            v-for="item in group.items"
            :key="item.path"
            :to="item.path"
            :class="['nav-link', { active: active(item.path) }]"
            :aria-current="active(item.path) ? 'page' : undefined"
            ><Icon :name="item.icon" :size="19" />{{ item.title }}</RouterLink
          >
        </div>
      </nav>
      <div class="sidebar-bottom">
        <Icon name="shield" :size="16" /><span>{{
          { admin: "管理员", auditor: "审计员", user: "成员" }[
            session.user?.role
          ] || "成员"
        }}</span>
      </div>
    </aside>
    <div class="app-body">
      <header class="topbar">
        <div class="actions">
          <button
            class="icon-button mobile-menu"
            aria-label="打开导航"
            @click="mobileNav = true"
          >
            <Icon name="menu" />
          </button>
          <div class="breadcrumb" aria-label="当前位置"><strong>{{ route.meta.title }}</strong></div>
        </div>
        <div class="topbar-right">
          <details class="account-menu">
            <summary>
              <span class="avatar">{{
                session.user?.username?.slice(0, 1)?.toUpperCase() || "U"
              }}</span
              ><span>{{ session.user?.username }}</span
              ><Icon name="down" :size="14" />
            </summary>
            <div class="account-popover">
              <span class="muted">{{ session.user?.email }}</span
              ><button class="text-button" @click="logout">
                <Icon name="logout" :size="16" />退出登录
              </button>
            </div>
          </details>
        </div>
      </header>
      <main id="main" class="app-main" tabindex="-1">
        <RouterView :key="route.path" />
      </main>
    </div>
    <el-drawer v-model="mobileNav" title="导航" direction="ltr" size="280px"
      ><nav aria-label="移动导航">
        <div v-for="group in groups" :key="group.label" class="nav-group">
          <div class="nav-label">{{ group.label }}</div>
          <RouterLink
            v-for="item in group.items"
            :key="item.path"
            :to="item.path"
            :class="['nav-link', { active: active(item.path) }]"
            :aria-current="active(item.path) ? 'page' : undefined"
            ><Icon :name="item.icon" :size="19" />{{ item.title }}</RouterLink
          >
        </div>
      </nav></el-drawer
    >
  </div>
</template>
