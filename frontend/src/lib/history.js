const pattern = /^[A-Za-z0-9_.-]{1,64}$/;
export const validRunId = (id) => typeof id === "string" && pattern.test(id);
const key = (userId) => `aiops:runs:v2:${userId}`;
export function getHistory(userId) {
  try {
    const rows = JSON.parse(localStorage.getItem(key(userId)) || "[]");
    const seen = new Set();
    return Array.isArray(rows) ? rows.filter((row) => {
      if (!row || !validRunId(row.thread_id) || seen.has(row.thread_id)) return false;
      seen.add(row.thread_id);
      return true;
    }).slice(0, 100) : [];
  } catch {
    return [];
  }
}
export function rememberRun(userId, row) {
  if (!userId || !validRunId(row.thread_id)) return;
  const rows = getHistory(userId);
  const old = rows.find((item) => item.thread_id === row.thread_id);
  const saved = { ...old, ...row, updated_at: row.updated_at || old?.updated_at || new Date().toISOString() };
  try {
    localStorage.setItem(
      key(userId),
      JSON.stringify(
        [
          saved,
          ...rows.filter((item) => item.thread_id !== row.thread_id),
        ].slice(0, 100),
      ),
    );
  } catch {
    /* Storage quota leaves the saved server run available by ID. */
  }
}

export function forgetRun(userId, id) {
  localStorage.setItem(key(userId), JSON.stringify(getHistory(userId).filter(row => row.thread_id !== id)));
}

export function readDraft(userId) {
  try { return JSON.parse(sessionStorage.getItem(`aiops:draft:${userId}`) || "null"); }
  catch { return null; }
}
export function writeDraft(userId, draft) {
  if (!userId) return;
  try {
    if (draft) sessionStorage.setItem(`aiops:draft:${userId}`, JSON.stringify(draft));
    else sessionStorage.removeItem(`aiops:draft:${userId}`);
  } catch { /* The form stays usable when browser storage is unavailable. */ }
}

export function readWorkspace(userId, runId) {
  if (!userId || !validRunId(runId)) return null;
  try {
    const saved = JSON.parse(sessionStorage.getItem(`aiops:view:${userId}:${runId}`) || "null");
    return saved && ["report", "process", "evidence", "causes"].includes(saved.tab) ? saved : null;
  } catch { return null; }
}
export function writeWorkspace(userId, runId, view) {
  if (!userId || !validRunId(runId)) return;
  try { sessionStorage.setItem(`aiops:view:${userId}:${runId}`, JSON.stringify(view)); }
  catch { /* Navigation stays available without session storage. */ }
}
