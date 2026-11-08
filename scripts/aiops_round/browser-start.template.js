async page => {
  const login = {username: __USERNAME__, password: __PASSWORD__};
  const symptom = "edge 的 /api/availability 业务请求失败，请只读调查原因；引用证据，说明处理和复测方法及仍未知之处。";
  const dir = __ROUND_DIR__;
  let postCount = 0;
  page.on('request', r => {
    if (r.method() === 'POST' && r.url().endsWith('/api/v1/aiops')) postCount += 1;
  });
  await page.getByRole('textbox', {name:'用户名', exact:true}).fill(login.username);
  await page.getByRole('textbox', {name:'密码', exact:true}).fill(login.password);
  await page.getByRole('button', {name:'登录', exact:true}).click();
  await page.waitForURL('**/dashboard');
  await page.goto('http://127.0.0.1:8200/aiops');
  await page.getByRole('button',{name:'开始诊断',exact:true}).waitFor();
  await page.locator('textarea').fill(symptom);
  const responsePromise = page.waitForResponse(
    r => r.url().endsWith('/api/v1/aiops') && r.request().method() === 'POST',
    {timeout: 120000});
  await page.getByRole('button',{name:'开始诊断',exact:true}).click();
  const response = await responsePromise;
  const status = response.status();
  await page.waitForTimeout(6000);
  const bodyText = await page.evaluate(() => document.body.innerText.slice(0, 3000));
  await page.screenshot({path: dir + "\\start.png", fullPage: true});
  return {clicked: 1, post_count: postCount, post_status: status, snapshot: bodyText};
}
