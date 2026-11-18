import { createRouter, createWebHistory } from "vue-router";
import { session } from "./lib/session";

export const navigation = [
  {
    label: "工作空间",
    items: [
      { path: "/dashboard", title: "工作台", icon: "overview" },
      { path: "/aiops", title: "故障诊断", icon: "pulse" },
      { path: "/aiops/history", title: "最近诊断", icon: "history" },
      { path: "/chat", title: "知识问答", icon: "chat" },
    ],
  },
  {
    label: "知识与应用",
    items: [
      { path: "/knowledge-bases", title: "知识库", icon: "book" },
      { path: "/assistants", title: "助手", icon: "spark" },
      { path: "/agents", title: "智能体", icon: "workflow" },
      { path: "/evaluation", title: "效果评测", icon: "chart" },
    ],
  },
  {
    label: "系统管理",
    items: [
      { path: "/monitor", title: "文档任务", icon: "tasks" },
      { path: "/storage", title: "文件管理", icon: "folder" },
      { path: "/platform", title: "运行状态", icon: "server" },
      { path: "/users", title: "用户管理", icon: "users", admin: true },
    ],
  },
];

const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: "/", redirect: "/dashboard" },
    {
      path: "/login",
      component: () => import("./views/Login.vue"),
      meta: { public: true, title: "登录" },
    },
    {
      path: "/dashboard",
      component: () => import("./views/Dashboard.vue"),
      meta: { title: "工作台" },
    },
    {
      path: "/aiops",
      component: () => import("./views/Diagnosis.vue"),
      meta: { title: "故障诊断" },
    },
    {
      path: "/aiops/history",
      component: () => import("./views/DiagnosisHistory.vue"),
      meta: { title: "最近诊断" },
    },
    {
      path: "/chat",
      component: () => import("./views/Chat.vue"),
      meta: { title: "知识问答" },
    },
    {
      path: "/knowledge-bases",
      component: () => import("./views/KnowledgeBases.vue"),
      meta: { title: "知识库" },
    },
    {
      path: "/knowledge-bases/:id",
      component: () => import("./views/KnowledgeDetail.vue"),
      meta: { title: "文档与检索" },
    },
    {
      path: "/assistants",
      component: () => import("./views/Applications.vue"),
      props: { kind: "assistants" },
      meta: { title: "助手" },
    },
    {
      path: "/agents",
      component: () => import("./views/Applications.vue"),
      props: { kind: "agents" },
      meta: { title: "智能体" },
    },
    {
      path: "/evaluation",
      component: () => import("./views/Evaluation.vue"),
      meta: { title: "效果评测" },
    },
    {
      path: "/monitor",
      component: () => import("./views/Tasks.vue"),
      meta: { title: "文档任务" },
    },
    {
      path: "/storage",
      component: () => import("./views/Storage.vue"),
      meta: { title: "文件管理" },
    },
    {
      path: "/platform",
      component: () => import("./views/Platform.vue"),
      meta: { title: "运行状态" },
    },
    { path: "/queue-monitor", redirect: "/platform?tab=queues" },
    {
      path: "/users",
      component: () => import("./views/Users.vue"),
      meta: { title: "用户管理", admin: true },
    },
    {
      path: "/:pathMatch(.*)*",
      component: () => import("./views/NotFound.vue"),
      meta: { title: "页面不存在" },
    },
  ],
  scrollBehavior: () => ({ top: 0 }),
});
router.beforeEach(async (to) => {
  if (to.meta.public) return true;
  if (!localStorage.getItem("token"))
    return { path: "/login", query: { redirect: to.fullPath } };
  try {
    await session.load();
  } catch {
    return { path: "/login", query: { redirect: to.fullPath } };
  }
  if (to.meta.admin && session.user?.role !== "admin") return "/dashboard";
});
router.afterEach((to) => {
  document.title = `${to.meta.title || "工作空间"} · AIOps`;
});
export default router;
