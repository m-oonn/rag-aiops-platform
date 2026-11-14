async page => {
  const errors = [];
  const checks = [];
  page.on('pageerror', error => errors.push(error.message));
  const tabs = ['报告总览', '候选原因 7', '现场证据 10', '排查过程'];
  for (const width of [1440, 768, 390, 360]) {
    await page.setViewportSize({width, height: width > 700 ? 1000 : 844});
    await page.reload();
    for (const name of tabs) {
      await page.getByRole('tab', {name, exact:true}).click();
      const result = await page.evaluate(() => ({
        width: innerWidth, content: document.documentElement.scrollWidth,
        replacementCharacter: document.body.innerText.includes('\uFFFD')
      }));
      if (result.content > width || result.replacementCharacter) throw new Error(JSON.stringify({name,...result}));
      checks.push({width, view:name, overflow:false, replacementCharacter:false});
    }
    await page.getByRole('tab', {name:'候选原因 7', exact:true}).click();
    const values = await page.locator('#candidate-select option').evaluateAll(options => options.map(o=>o.value));
    for (let index=0; index<values.length; index++) {
      if (width <= 700) await page.locator('#candidate-select').selectOption(values[index]);
      else await page.locator('.candidate-list>button').nth(index).click();
      if (!await page.locator('.candidate-heading h2').innerText()) throw new Error('候选详情为空');
    }
    await page.getByRole('tab', {name:'现场证据 10', exact:true}).click();
    const evidence = await page.locator('#evidence-select option').evaluateAll(options => options.map(o=>o.value));
    for (let index=0; index<evidence.length; index++) {
      if (width <= 700) await page.locator('#evidence-select').selectOption(evidence[index]);
      else await page.locator('.evidence-list>button').nth(index).click();
      if (!await page.locator('.evidence-conclusion').innerText()) throw new Error('证据详情为空');
    }
    await page.locator('.excerpt summary').click();
    if (!await page.locator('.excerpt pre').isVisible()) throw new Error('节选未展开');
    checks.push({width, candidates:values.length, evidence:evidence.length, excerpt:true});
  }
  await page.getByRole('tab',{name:'排查过程',exact:true}).click();
  await page.getByRole('button',{name:'播放回放',exact:true}).click();
  await page.waitForFunction(()=>document.querySelector('.replay-progress>span').textContent==='E02');
  await page.getByRole('button',{name:'暂停回放',exact:true}).click();
  if (!await page.locator('#panel-process').isVisible()) throw new Error('播放时跳页');
  await page.locator('.collection-list button').last().click();
  if (!await page.getByRole('button',{name:'下一项',exact:true}).isDisabled()) throw new Error('终点仍能前进');
  await page.getByRole('button',{name:'查看证据详情',exact:true}).click();
  if (!(await page.locator('.evidence-heading').innerText()).includes('E10')) throw new Error('证据跳转不匹配');
  await page.getByRole('tab',{name:'排查过程',exact:true}).click();
  await page.getByRole('button',{name:'播放回放',exact:true}).click();
  await page.getByRole('tab',{name:'报告总览',exact:true}).click();
  await page.getByRole('tab',{name:'排查过程',exact:true}).click();
  if (!await page.getByRole('button',{name:'播放回放',exact:true}).isVisible()) throw new Error('切页没有暂停');
  checks.push({replay:{play:true,pause:true,detail:'E10',endDisabled:true,stopOnTabChange:true}});
  await page.emulateMedia({reducedMotion:'reduce'});
  await page.reload();
  if (!await page.evaluate(()=>matchMedia('(prefers-reduced-motion: reduce)').matches)) throw new Error('减少动效模拟失败');
  await page.getByRole('tab',{name:'候选原因 7',exact:true}).click();
  await page.locator('#candidate-select').selectOption({label:'H2 · localapp 下游端点配置错配 · 待验证'});
  await page.locator('.candidate-heading h2').waitFor();
  await page.screenshot({path:'demos/aiops-design-lab/artifacts/candidates-mobile.png',fullPage:true});
  await page.emulateMedia({reducedMotion:'no-preference'});
  await page.setViewportSize({width:1440,height:1000});
  await page.reload();
  await page.getByRole('tab',{name:'候选原因 7',exact:true}).click();
  await page.locator('.candidate-list>button').nth(5).click();
  await page.screenshot({path:'demos/aiops-design-lab/artifacts/candidates-desktop.png',fullPage:true});
  await page.getByRole('tab',{name:'现场证据 10',exact:true}).click();
  await page.locator('.evidence-list>button').last().click();
  await page.screenshot({path:'demos/aiops-design-lab/artifacts/evidence-desktop.png',fullPage:true});
  await page.getByRole('tab',{name:'报告总览',exact:true}).click();
  await page.screenshot({path:'demos/aiops-design-lab/artifacts/overview-desktop.png',fullPage:true});
  if (errors.length) throw new Error(errors.join('\n'));
  return {checks, reducedMotion:true, runtimeErrors:errors};
}
