export function breakdown(rows, keyOf, labelOf = key => key, toneOf = () => 'info') {
  const counts = new Map();
  for (const row of rows) {
    const key = keyOf(row);
    if (!counts.has(key)) counts.set(key, { key, label: labelOf(key), tone: toneOf(key), count: 0 });
    counts.get(key).count++;
  }
  return [...counts.values()];
}
