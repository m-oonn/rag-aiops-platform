export function snapshotSteps(snapshots = []) {
  const steps = [];
  const add = (text, done = false, result = "", occurrence = 1) => {
    if (typeof text !== "string" || !text.trim()) return;
    text = text.replace(/^\[并行\]\s*/, "");
    const pending = steps.filter((step) => step.text === text && !step.done);
    const existing = done ? pending[0] : pending[occurrence - 1];
    if (existing) {
      existing.done ||= done;
      if (result) existing.result = result;
    } else steps.push({ text, done, result });
  };
  for (const snapshot of snapshots) {
    if (!snapshot) continue;
    if (typeof snapshot === "string") {
      add(snapshot, true);
      continue;
    }
    const payload = snapshot.payload || {};
    if (snapshot.node === "executor")
      add(payload.last_step, true, payload.result_digest || "");
    else {
      const occurrences = new Map();
      for (const text of payload.plan || payload.remaining_plan || []) {
        if (typeof text !== "string") continue;
        const normalized = text.replace(/^\[并行\]\s*/, "");
        occurrences.set(normalized, (occurrences.get(normalized) || 0) + 1);
        add(text, false, "", occurrences.get(normalized));
      }
    }
  }
  return steps;
}

export function approvalUrl(value) {
  try {
    const url = new URL(value);
    return ["http:", "https:"].includes(url.protocol) ? url.href : "";
  } catch {
    return "";
  }
}

export function candidateRows(investigation, hypotheses = []) {
  return (investigation?.candidates || investigation?.hypotheses || hypotheses)
    .map((item, index) => ({
      id: item.id || String(index),
      text:
        item.explanation || item.hypothesis || item.name || item.cause || "",
      status:
        {
          supported: "有证据支持",
          excluded: "已排除",
          unresolved: "待验证",
          active: "待验证",
          pending: "待验证",
        }[item.status || item.state] || "待验证",
      evidence: item.evidence_ids || [],
    }))
    .filter((item) => item.text);
}
