import { ref, onMounted, onUnmounted } from "vue";
import { ElMessage, ElMessageBox } from "element-plus";

export const notify = (message) => ElMessage.success(message);
export const fail = (error) =>
  ElMessage.error(error?.message || "操作失败，请重试");
export async function confirmAction(
  title,
  message,
  button = "确认",
  danger = false,
) {
  try {
    await ElMessageBox.confirm(message, title, {
      confirmButtonText: button,
      cancelButtonText: "取消",
      type: danger ? "warning" : "info",
      closeOnClickModal: false,
      autofocus: false,
    });
    return true;
  } catch {
    return false;
  }
}
export function useLoad(load, { interval = 0 } = {}) {
  const loading = ref(false),
    error = ref("");
  let alive = true,
    timer;
  async function refresh(quiet = false) {
    if (loading.value || !alive) return;
    if (!quiet) loading.value = true;
    try {
      await load();
      error.value = "";
    } catch (e) {
      if (alive) error.value = e.message;
    } finally {
      loading.value = false;
    }
  }
  onMounted(() => {
    refresh();
    if (interval)
      timer = setInterval(() => {
        if (!document.hidden) refresh(true);
      }, interval);
  });
  onUnmounted(() => {
    alive = false;
    clearInterval(timer);
  });
  return { loading, error, refresh };
}
export const dateTime = (value) => {
  if (!value) return "—";
  const date = new Date(value);
  return Number.isNaN(date.getTime())
    ? "—"
    : date.toLocaleString("zh-CN", {
        month: "2-digit",
        day: "2-digit",
        hour: "2-digit",
        minute: "2-digit",
      });
};
export const fileSize = (bytes) =>
  bytes == null
    ? "—"
    : bytes < 1024
      ? `${bytes} B`
      : bytes < 1048576
        ? `${(bytes / 1024).toFixed(1)} KB`
        : `${(bytes / 1048576).toFixed(1)} MB`;
export const docStatus = (value) =>
  ({
    0: "待处理",
    1: "处理中",
    2: "已完成",
    3: "失败",
    PENDING: "待处理",
    PROCESSING: "处理中",
    STARTED: "处理中",
    RETRY: "重试中",
    SUCCESS: "已完成",
    FAILURE: "失败",
  })[value] ||
  value ||
  "未知";
export const runStatus = (value) =>
  ({
    idle: "未开始",
    running: "诊断中",
    loading: "正在读取",
    unavailable: "暂不可读取",
    approved: "复核通过，继续处理中",
    rejected: "已退回，继续补查中",
    completed: "已完成",
    failed: "失败",
    disconnected: "连接已断开",
    pending_terminal: "等待审批",
    pending_review: "等待复核",
  })[value] ||
  value ||
  "未知";
export const evalStatus = (value) =>
  ({ 0: "待处理", 1: "执行中", 2: "已完成", 3: "失败", 4: "待评测" })[value] ||
  "未知";
export const tone = (value) =>
  ["ok", "completed", "SUCCESS", 2, "supported", "confirmed_cause"].includes(
    value,
  )
    ? "success"
    : ["failed", "unavailable", "error", "FAILURE", 3, "excluded"].includes(
          value,
        )
      ? "danger"
      : ["running", "PROCESSING", 1].includes(value)
        ? "info"
        : "muted";
