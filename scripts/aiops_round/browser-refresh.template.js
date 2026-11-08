async page => {
  const dir = __ROUND_DIR__;
  const threadId = __THREAD__;
  let aiopsPost = 0;
  page.on('request', r => {
    if (r.method() === 'POST' && r.url().endsWith('/api/v1/aiops')) aiopsPost += 1;
  });
  await page.reload();
  await page.getByRole('button', {name:'开始诊断', exact:true}).waitFor();
  await page.waitForFunction(
    (tid) => localStorage.getItem('aiops_last_thread') === tid, threadId, {timeout: 30000});
  await page.waitForTimeout(4000);
  const reportVisible = await page.evaluate(() => {
    const el = document.getElementById('report-card');
    if (!el) return {found: false};
    const text = el.innerText || '';
    return {found: true, length: text.length, head: text.slice(0, 400)};
  });
  const evidenceCount = await page.evaluate(() => {
    const nodes = document.querySelectorAll('[class*="evidence"]');
    return nodes.length;
  });
  await page.screenshot({path: dir + "\\after-refresh.png", fullPage: true});
  return {refreshed: true, stored_thread: threadId, report: reportVisible,
          evidence_nodes: evidenceCount, aiops_post_after_refresh: aiopsPost};
}
