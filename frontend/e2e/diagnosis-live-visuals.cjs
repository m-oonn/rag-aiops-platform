const path = require('node:path');
const fs = require('node:fs/promises');
const { chromium } = require(path.join(process.env.APPDATA, 'npm/node_modules/@playwright/cli/node_modules/playwright'));
async function verify(page) {
  const login = JSON.parse(await fs.readFile('D:/ragPdfSystem++agent/runtime/aiops-manual-20261114-b/login.json', 'utf8'));
  const errors = [], writes = [];
  page.on('pageerror', error => errors.push(error.message));
  await page.route('**/api/v1/**', async route => {
    const request = route.request();
    if (request.method() !== 'GET') {
      writes.push(`${request.method()} ${new URL(request.url()).pathname}`);
      return route.abort();
    }
    const upstream = new URL(request.url());
    upstream.port = '8201';
    const response = await route.fetch({ url: upstream.href });
    await route.fulfill({ response });
  });
  const auth = await page.context().request.post('http://127.0.0.1:8201/api/v1/auth/login/access-token', { form: login });
  if (!auth.ok()) throw new Error('Local test login failed');
  const token = (await auth.json()).access_token;
  const meResponse = await page.context().request.get('http://127.0.0.1:8201/api/v1/auth/me', { headers: { Authorization: `Bearer ${token}` } });
  const role = (await meResponse.json()).role;
  await page.goto('http://127.0.0.1:5273/login');
  await page.evaluate(value => localStorage.setItem('token', value), token);
  await page.goto('http://127.0.0.1:5273/aiops?run=web-b1045746-d354-4383-8-3f3a09cd77344930a9c4bb15c7ec59f4');
  await page.getByText('故障层已定位 · 原因待确认', { exact: true }).waitFor();
  await page.setViewportSize({ width: 1440, height: 1080 });
  await page.screenshot({ path: 'D:/ragPdfSystem++agent/runtime/aiops-readable-report.png', fullPage: true });
  const check = (pass, message) => { if (!pass) errors.push(message); };
  const reading = { candidates: [], evidence: [] };
  const internalMarkers = /[a-f0-9]{24,64}|controlled_stop|shutdown_completed|TimeoutError|process_present|listening ==|downstream_port|upstream_timeout_seconds|\uFFFD|锟斤|銆|鐨/;
  await page.getByRole('tab', { name: /候选原因/ }).click();
  for (let index = 0; index < 7; index++) {
    await page.locator('.candidate-index button').nth(index).click();
    const heading = await page.locator('.candidate-detail h2').innerText();
    const visible = await page.locator('.candidate-detail').innerText();
    check(!internalMarkers.test(visible), `Unreadable candidate H${index + 1}: ${visible}`);
    reading.candidates.push({ number: index + 1, heading, visible });
    if (index === 5) {
      await page.getByText('候选原始描述', { exact: true }).click();
      check((await page.locator('.candidate-detail').innerText()).includes('5bd350547f6d4968b03a36c3acb46b31'), 'Original candidate instance was lost');
      await page.getByText('候选原始描述', { exact: true }).click();
    }
  }
  await page.getByRole('tab', { name: /现场证据/ }).click();
  const evidenceButtons = page.locator('.evidence-index button');
  for (let index = 0; index < await evidenceButtons.count(); index++) {
    await evidenceButtons.nth(index).click();
    const visible = await page.locator('.evidence-detail').innerText();
    check(!internalMarkers.test(visible), `Unreadable evidence ${index + 1}: ${visible}`);
    reading.evidence.push({ heading: await page.locator('.evidence-heading').innerText(), visible });
    if (visible.includes('下游请求超时（秒）')) {
      await page.screenshot({ path: 'D:/ragPdfSystem++agent/runtime/aiops-readable-configuration.png', fullPage: true });
    }
  }
  await page.getByRole('tab', { name: /排查过程/ }).click();
  check(await page.locator('.check-list li').count() === 10, 'Actual observations are not ten');
  await page.getByRole('button', { name: '回放', exact: true }).click();
  await page.waitForFunction(() => document.querySelector('[aria-current="step"] .check-number')?.textContent === '02');
  await page.getByRole('button', { name: '暂停', exact: true }).click();
  await page.getByRole('button', { name: '下一项', exact: true }).click();
  check((await page.locator('[aria-current="step"] .check-number').textContent()) === '03', 'Replay next control failed');
  await page.locator('.check-list li').last().getByRole('button').click();
  check(await page.getByRole('button', { name: '重新回放', exact: true }).isVisible(), 'Replay end is not stopped');
  await page.screenshot({ path: 'D:/ragPdfSystem++agent/runtime/aiops-readable-process.png', fullPage: true });
  await page.getByRole('button', { name: '查看证据', exact: true }).click();
  check((await page.locator('.event-chain li').count()) === 3, 'Stopped service event chain is not three events');
  check((await page.locator('.evidence-heading').textContent()).includes('E10'), 'Replay did not navigate to E10');
  await page.screenshot({ path: 'D:/ragPdfSystem++agent/runtime/aiops-readable-evidence.png', fullPage: true });
  await page.getByRole('button', { name: '来源与原文', exact: true }).click();
  await page.getByRole('dialog').getByText('观测', { exact: true }).waitFor();
  if (['admin', 'auditor'].includes(role)) {
    await page.getByRole('button', { name: '读取现场原文', exact: true }).click();
    check(await page.getByText('已读取原文', { exact: true }).isVisible(), 'Authorized raw evidence unavailable');
  } else {
    check(await page.getByRole('button', { name: '读取现场原文', exact: true }).count() === 0, 'Ordinary user can read raw evidence');
    check(!(await page.getByRole('dialog').textContent()).includes('raw_ref'), 'Internal source reference leaked');
  }
  await page.keyboard.press('Escape');
  await page.getByRole('tab', { name: /候选原因/ }).click();
  check((await page.locator('.candidate-index button').count()) === 7, 'Seven saved candidates not restored');
  await page.locator('.candidate-index button').filter({ hasText: 'H6' }).click();
  check((await page.locator('.candidate-detail').textContent()).includes('待验证'), 'Leading candidate was upgraded');
  await page.screenshot({ path: 'D:/ragPdfSystem++agent/runtime/aiops-readable-causes.png', fullPage: true });
  await page.locator('.candidate-index button').filter({ hasText: 'H4' }).click();
  check((await page.locator('.candidate-detail').textContent()).includes('已排除'), 'Excluded candidate lost status');
  check(await page.locator('.candidate-gap').count() === 0, 'Excluded candidate still asks for verification');
  check((await page.locator('.relation-node.contradict').count()) === 1, 'Explicit contradiction not rendered');
  await page.locator('.relation-node').click();
  check((await page.locator('.evidence-heading').textContent()).includes('E09'), 'Candidate evidence navigation failed');
  await page.reload();
  await page.getByText('故障层已定位 · 原因待确认', { exact: true }).waitFor();
  check((await page.getByRole('tab', { name: /现场证据/ }).textContent()).includes('10'), 'Refresh lost evidence');
  await page.getByRole('tab', { name: /诊断报告/ }).focus();
  await page.keyboard.press('ArrowRight');
  check((await page.locator('[role="tab"][aria-selected="true"]').textContent()).includes('排查过程'), 'Keyboard tab navigation failed');
  await page.keyboard.press('Home');
  check((await page.locator('[role="tab"][aria-selected="true"]').textContent()).includes('诊断报告'), 'Keyboard Home failed');
  const widths = [];
  for (const width of [1040, 736, 320]) {
    await page.setViewportSize({ width, height: 960 });
    for (const name of ['诊断报告', '排查过程', '现场证据', '候选原因']) {
      await page.getByRole('tab', { name: new RegExp(name) }).click();
      const overflow = await page.evaluate(() => document.documentElement.scrollWidth > innerWidth);
      if (overflow) errors.push(`Horizontal overflow at ${width} on ${name}`);
      widths.push({ width, tab: name, overflow });
    }
  }
  await page.emulateMedia({ reducedMotion: 'reduce' });
  await page.getByRole('tab', { name: /诊断报告/ }).click();
  check((await page.locator('.workspace-panel').evaluate(element => getComputedStyle(element).animationName)) === 'none', 'Reduced motion did not suppress animation');
  await page.screenshot({ path: 'D:/ragPdfSystem++agent/runtime/aiops-readable-mobile.png', fullPage: true });
  check(writes.length === 0, 'Unexpected product write requested');
  const result = { errors, writes, widths, reading, actualRecords: 10, candidates: 7, refreshed: true, role };
  await fs.writeFile('D:/ragPdfSystem++agent/runtime/aiops-readable-browser-check.json', JSON.stringify(result, null, 2));
  console.log(JSON.stringify(result));
  if (errors.length) throw new Error(errors.join('\n'));
}
(async () => {
  const browser = await chromium.launch({ channel: 'chrome', headless: true });
  try {
    const page = await browser.newPage();
    page.setDefaultTimeout(12000);
    await verify(page);
  } finally { await browser.close(); }
})().catch(error => { console.error(error.message); process.exitCode = 1; });
