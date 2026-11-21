export function advanceSteps(steps, snapshot) {
  if (!snapshot) return steps;
  const payload = typeof snapshot === "string" ? { last_step: snapshot } : snapshot.payload || {};
  if (typeof snapshot === "string" || ["executor", "terminal_review"].includes(snapshot.node)) {
    if (Array.isArray(payload.completed_steps) && payload.completed_steps.length) {
      return payload.completed_steps.reduce((rows, item) => advanceSteps(rows, {node: "executor", payload: item || {}}), steps);
    }
    if (typeof payload.last_step !== "string" || !payload.last_step.trim()) return steps;
    const text = payload.last_step.replace(/^\[并行\]\s*/, "");
    const index = steps.findIndex(step => step.text === text && !step.done);
    const row = { text, done: true, result: payload.result_digest || "" };
    return index < 0 ? [...steps, row] : steps.map((step, i) => i === index ? row : step);
  }
  const plan = payload.plan || payload.remaining_plan;
  if (!Array.isArray(plan)) return steps;
  return [...steps.filter(step => step.done), ...plan.filter(text => typeof text === "string" && text.trim())
    .map(text => ({ text: text.replace(/^\[并行\]\s*/, ""), done: false, result: "" }))];
}

export function snapshotSteps(snapshots = []) {
  let steps = [];
  for (const snapshot of snapshots) {
    steps = advanceSteps(steps, snapshot);
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
