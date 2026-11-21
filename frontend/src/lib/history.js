const pattern = /^[A-Za-z0-9_.-]{1,64}$/;
export const validRunId = (id) => typeof id === "string" && pattern.test(id);
const key = (userId) => `aiops:runs:v2:${userId}`;
const hiddenKey = userId => `aiops:hidden-runs:v1:${userId}`;
const updateTime = row => typeof row.updated_at === 'string' ? Date.parse(row.updated_at) || 0 : 0;
export const recentFirst = rows => rows.sort((a, b) => updateTime(b) - updateTime(a));
function hiddenRuns(userId) {
  try {
    const rows = JSON.parse(localStorage.getItem(hiddenKey(userId)) || "[]");
    return new Set(Array.isArray(rows) ? rows.filter(validRunId) : []);
  } catch { return new Set(); }
}
export function getHistory(userId) {
  try {
    const rows = JSON.parse(localStorage.getItem(key(userId)) || "[]");
    const hidden = hiddenRuns(userId);
    const seen = new Set();
    return Array.isArray(rows) ? recentFirst(rows.filter((row) => {
      if (!row || !validRunId(row.thread_id) || hidden.has(row.thread_id) || seen.has(row.thread_id)) return false;
      seen.add(row.thread_id);
      return true;
    })).slice(0, 100) : [];
  } catch {
    return [];
  }
}
export function rememberRun(userId, row) {
  if (!userId || !validRunId(row.thread_id)) return;
  if (hiddenRuns(userId).has(row.thread_id)) return;
  const rows = getHistory(userId);
  const old = rows.find((item) => item.thread_id === row.thread_id);
  const saved = { ...old, ...row, updated_at: row.updated_at || old?.updated_at || new Date().toISOString() };
  const next = old ? rows.map(item => item.thread_id === row.thread_id ? saved : item) : [saved, ...rows];
  try {
    localStorage.setItem(
      key(userId),
      JSON.stringify(recentFirst(next).slice(0, 100)),
    );
  } catch {
    /* Storage quota leaves the saved server run available by ID. */
  }
}

export function markHistoryRunUnavailable(row, error) {
  return {
    ...row,
    diagnosis: null,
    investigation: null,
    knowledge_references: [],
    details_status: "unavailable",
    readError: error?.message || String(error || "详情暂不可读取"),
  };
}

export function mergeHistoryRun(saved, run) {
  const detailsUnavailable = ["unavailable", "missing"].includes(run.details_status);
  return {
    ...saved,
    ...run,
    diagnosis: Object.hasOwn(run, "diagnosis")
      ? run.diagnosis
      : detailsUnavailable ? null : saved?.diagnosis ?? null,
    details_status: run.details_status || "available",
    query: run.query || saved?.query || "",
    readError: "",
  };
}

export function mergeHistoryList(localRows, serverRows, userId, maxResults = 100) {
  const limit = Number.isFinite(maxResults) ? Math.max(0, Math.trunc(maxResults)) : 100;
  const hidden = hiddenRuns(userId);
  const visible = row => validRunId(row?.thread_id) && !hidden.has(row.thread_id);
  localRows = localRows.filter(visible);
  if (!Array.isArray(serverRows)) return recentFirst(localRows).slice(0, limit);
  const localById = new Map(localRows.map(row => [row.thread_id, row]));
  const serverIds = new Set();
  const recovered = serverRows.filter(row => {
    if (!visible(row) || serverIds.has(row.thread_id)) return false;
    serverIds.add(row.thread_id);
    return true;
  }).map(row => mergeHistoryRun(localById.get(row.thread_id), row));
  return recentFirst([...recovered, ...localRows.filter(row => !serverIds.has(row.thread_id))]).slice(0, limit);
}

export function forgetRun(userId, id) {
  if (!userId || !validRunId(id)) return;
  const hidden = hiddenRuns(userId);
  hidden.add(id);
  localStorage.setItem(hiddenKey(userId), JSON.stringify([...hidden]));
}

export function readDraft(userId) {
  if (!userId) return null;
  try {
    const saved = JSON.parse(sessionStorage.getItem(`aiops:draft:${userId}`) || "null");
    return saved && typeof saved.query === 'string'
      ? {query:saved.query.slice(0, 12000), terminalEnabled:saved.terminalEnabled === true} : null;
  }
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

export function readReviewDraft(userId, runId) {
  if (!userId || !validRunId(runId)) return "";
  try {
    const value = JSON.parse(sessionStorage.getItem(`aiops:review:${userId}:${runId}`) || '""');
    return typeof value === "string" ? value.slice(0, 4000) : "";
  } catch { return ""; }
}
export function writeReviewDraft(userId, runId, note) {
  if (!userId || !validRunId(runId)) return;
  try {
    const key = `aiops:review:${userId}:${runId}`;
    if (note) sessionStorage.setItem(key, JSON.stringify(note.slice(0, 4000)));
    else sessionStorage.removeItem(key);
  } catch { /* A failed storage write must not erase the visible review note. */ }
}

export function readExperienceDraft(userId, runId, candidate) {
  if (!userId || !validRunId(runId) || !candidate?.id) return null;
  try {
    const saved = JSON.parse(sessionStorage.getItem(`aiops:experience:${userId}:${runId}`) || 'null');
    if (saved?.id !== candidate.id || saved.version !== candidate.version || saved.status !== candidate.status) return null;
    return {kbId: typeof saved.kbId === 'string' ? saved.kbId : '', note: typeof saved.note === 'string' ? saved.note.slice(0, 4000) : ''};
  } catch { return null; }
}
export function writeExperienceDraft(userId, runId, candidate, draft) {
  if (!userId || !validRunId(runId) || !candidate?.id) return;
  try {
    const key = `aiops:experience:${userId}:${runId}`;
    if (draft && (draft.note || draft.kbId)) {
      sessionStorage.setItem(key, JSON.stringify({id:candidate.id, version:candidate.version, status:candidate.status,
        kbId:String(draft.kbId || ''), note:String(draft.note || '').slice(0, 4000)}));
    } else sessionStorage.removeItem(key);
  } catch { /* Keep editing available when browser storage is unavailable. */ }
}
