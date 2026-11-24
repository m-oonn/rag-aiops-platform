export function documentStages(stats) {
  return [
    ['pending', '待处理', 'muted'], ['processing', '处理中', 'info'],
    ['completed', '已完成', 'success'], ['failed', '失败', 'danger'],
  ].flatMap(([key, label, tone]) => {
    const count = stats?.[`total_${key}`];
    return Number.isSafeInteger(count) && count >= 0 ? [{ key, label, tone, count }] : [];
  });
}
