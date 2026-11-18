async page => {
  const base = 'http://127.0.0.1:8768/';
  const output = 'D:/ragPdfSystem++agent/docs/prototypes/aiops-v1/';
  const results = [], errors = [], requests = [], badResponses = [];
  page.on('pageerror', error => errors.push(String(error)));
  page.on('console', message => { if (message.type() === 'error') errors.push(message.text()); });
  page.on('request', request => requests.push({url:request.url(),method:request.method()}));
  page.on('response', response => { if (response.status() >= 400) badResponses.push({url:response.url(),status:response.status()}); });
  const assert = (condition, message) => { if (!condition) throw new Error(message); };
  const text = selector => page.locator(selector).innerText();
  const check = async (name, fn) => {
    try { await fn(); results.push({name,status:'passed'}); }
    catch (error) { results.push({name,status:'failed',error:String(error)}); }
  };
  const nav = async name => {
    if (await page.locator('#drawer').isVisible()) await page.locator('#close-drawer').click();
    if (await page.locator('#menu-button').isVisible()) await page.locator('#menu-button').click();
    await page.locator(`[data-page="${name}"]`).click();
    if (await page.locator('#menu-button').isVisible()) await page.waitForFunction(()=>document.querySelector('#sidebar').getBoundingClientRect().right<=1);
  };
  await page.setViewportSize({width:1440,height:1100});
  await page.goto(base);
  await check('初始化与接口清单载入', async () => {
    assert((await text('#run-state')) === '诊断已完成','default state');
    assert((await text('#pane-report')).includes('confirmed_cause'),'default cause');
    assert(await page.evaluate(() => window.API_INVENTORY.route_count === 78),'route count');
    const duplicates = await page.evaluate(() => [...document.querySelectorAll('[id]')].map(el=>el.id).filter((id,i,ids)=>ids.indexOf(id)!==i));
    assert(duplicates.length === 0,'duplicate ids '+duplicates.join(','));
  });
  await check('四个诊断标签与键盘切换', async () => {
    for (const tab of ['process','candidates','evidence','report']) {
      await page.locator('#tab-'+tab).click();
      assert(await page.locator('#pane-'+tab).isVisible(),tab);
    }
    await page.locator('#tab-report').focus();
    await page.keyboard.press('ArrowRight');
    assert((await page.locator('#tab-process').getAttribute('aria-selected'))==='true','arrow navigation');
    await page.keyboard.press('Home');
  });
  await check('普通用户隐藏原文及抽屉焦点恢复', async () => {
    const source = page.locator('#pane-report [data-evidence]').first();
    await source.click();
    assert((await text('#drawer-body')).includes('普通用户查看脱敏元数据'),'redaction note');
    assert(await page.locator('#drawer-body pre').count()===0,'raw fields exposed');
    assert(await page.evaluate(()=>document.querySelector('.app').inert),'background inert');
    await page.locator('[data-action="account"]').click();
    await page.locator('#drawer .demo-role').selectOption('auditor');
    await page.keyboard.press('Escape');
    assert(await source.evaluate(el=>el===document.activeElement),'nested drawer focus return');
    await source.click();
    assert((await text('#drawer-body')).includes('示例原始字段'),'auditor raw fields');
    assert(await page.locator('#drawer-body pre').count()>0,'missing raw example');
    await page.keyboard.press('Escape');
    await page.locator('#account-button').click();
    await page.locator('#drawer .demo-role').selectOption('user');
    await page.keyboard.press('Escape');
  });
  await check('五个预设场景与服务关系无错误继承', async () => {
    const expected={stopped:'confirmed_cause',config:'localized_fault',latency:'localized_fault',approval:'pending_terminal_approval',failed:'未形成诊断结论'};
    for (const [scene, value] of Object.entries(expected)) {
      await page.locator('#scenario').selectOption(scene);
      assert((await text('#pane-report')).includes(value),scene+' outcome');
      if (scene!=='stopped') assert(await page.locator('.service-chain .fault-node').count()===0,scene+' inherited stopped fault');
    }
    await page.locator('#scenario').selectOption('approval');
    await page.locator('[data-action="approval"]').click();
    assert((await text('#drawer-body')).includes('由后端重新核验'),'approval contract');
    await page.keyboard.press('Escape');
  });
  await check('本地演示完成与中断、空描述校验', async () => {
    await page.locator('#scenario').selectOption('stopped');
    await page.locator('#run-button').click();
    assert((await text('#run-button')).includes('停止演示'),'running button');
    await page.waitForFunction(()=>document.querySelector('#run-state').textContent==='诊断已完成',{},{timeout:7000});
    await page.locator('#run-button').click();
    await page.locator('#run-button').click();
    assert((await text('#run-state')).includes('准备开始'),'stop state');
    await page.locator('#new-diagnosis').click();
    assert((await page.locator('#query').inputValue())==='','new query');
    assert(await page.locator('#copy-id').isDisabled(),'empty id');
    await page.locator('#run-button').click();
    assert((await text('#toast')).includes('请先描述'),'validation');
    await page.locator('#scenario').selectOption('stopped');
  });
  await check('最近记录搜索、等级筛选与按 ID 恢复', async () => {
    await nav('history');
    assert(await page.locator('#history-body tr').count()===3,'history initial');
    await page.locator('#history-filter').selectOption('confirmed_cause');
    assert(await page.locator('#history-body [data-open-scene]').count()===1,'history filter');
    await page.locator('#history-filter').selectOption('all');
    await page.locator('#history-search').fill('不存在的记录');
    assert((await text('#history-body')).includes('没有匹配'),'empty search');
    await page.locator('#history-search').fill('');
    await page.locator('#restore-id').fill('demo-stopped-001');
    await page.locator('#restore-form button').click();
    assert(await page.locator('#page-diagnosis').isVisible(),'restore destination');
    assert((await text('#run-id'))==='demo-stopped-001','restore id');
  });
  await check('知识库、片段演示及混合检索禁用', async () => {
    await nav('knowledge');
    await page.locator('[data-document="0"]').click();
    assert((await text('#drawer-body')).includes('第 1 块'),'document chunk');
    await page.keyboard.press('Escape');
    await page.locator('#retrieval-query').fill('<img src=x onerror=alert(1)>');
    await page.locator('#retrieval-button').click();
    assert((await text('#retrieval-results')).includes('<img src=x'),'escaped query text');
    assert(await page.locator('#retrieval-results img').count()===0,'html injection');
    await page.locator('[data-kb="cases"]').click();
    assert(await page.locator('#retrieval-button').isDisabled(),'hybrid unsupported');
    await page.locator('[data-kb="runbooks"]').click();
    await page.locator('#document-file').setInputFiles(output+'verification/原型校验.txt');
    assert((await text('#document-body')).includes('原型校验.txt'),'local registration');
    assert((await text('#document-body')).includes('仅本机登记'),'registration label');
    await page.locator('#new-kb').click();
    assert((await text('#drawer-title')).includes('POST /api/v1/knowledge-bases'),'creation contract');
    await page.keyboard.press('Escape');
  });
  await check('平台维护分类与角色切换', async () => {
    await nav('platform');
    assert((await text('#platform-content')).includes('未验证调用'),'dependency probe limit');
    await page.locator('[data-platform="ingestion"]').click();
    assert((await text('#platform-content')).includes('status=degraded'),'queue degraded');
    await page.locator('[data-platform="files"]').click();
    assert((await text('#platform-content')).includes('/storage/files'),'storage contract');
    await page.locator('[data-platform="account"]').click();
    await page.locator('#platform-content .demo-role').selectOption('admin');
    assert((await text('#profile-role'))==='管理员','role label');
    await page.locator('#account-button').click();
    const duplicates=await page.evaluate(()=>[...document.querySelectorAll('[id]')].map(e=>e.id).filter((id,i,a)=>a.indexOf(id)!==i));
    assert(duplicates.length===0,'account duplicate ids');
    await page.locator('#drawer .demo-role').selectOption('user');
    await page.keyboard.press('Escape');
  });
  await check('78 接口筛选、合同与 JSON 导出', async () => {
    await nav('interfaces');
    assert(await page.locator('#api-body [data-api]').count()===78,'all contracts');
    await page.locator('#api-module').selectOption('aiops');
    assert(await page.locator('#api-body [data-api]').count()===7,'aiops filter');
    await page.locator('#api-search').fill('continue');
    assert(await page.locator('#api-body [data-api]').count()===1,'continue search');
    await page.locator('#api-body [data-api]').click();
    assert((await text('#drawer-body')).includes('Termcp'),'continue contract');
    await page.keyboard.press('Escape');
    await page.locator('#api-search').fill('');
    await page.locator('#api-module').selectOption('all');
    const downloadPromise=page.waitForEvent('download');
    await page.locator('#download-inventory').click();
    const download=await downloadPromise;
    assert(download.suggestedFilename()==='aiops-api-inventory-20261113.json','export name');
    await download.saveAs(output+'verification/downloaded-inventory.json');
  });
  await check('设计说明抽屉', async () => {
    await page.locator('#design-button').click();
    assert((await text('#drawer-body')).includes('五模块'),'design module scope');
    await page.locator('[data-action="api-page"]').click();
    assert(await page.locator('#page-interfaces').isVisible(),'api page jump');
  });
  await check('五个页面在宽窄屏均无整页横向溢出', async () => {
    for (const width of [1440,1280,980,760,390]) {
      await page.setViewportSize({width,height:width===390?844:900});
      for (const name of ['diagnosis','history','knowledge','platform','interfaces']) {
        await nav(name);
        const size=await page.evaluate(()=>({scroll:document.documentElement.scrollWidth,client:document.documentElement.clientWidth}));
        assert(size.scroll<=size.client+1,`${width}px ${name}: ${JSON.stringify(size)}`);
      }
    }
  });
  await check('移动导航、抽屉与截图', async () => {
    await page.setViewportSize({width:390,height:844});
    await nav('diagnosis');
    await page.locator('#scenario').selectOption('stopped');
    await page.screenshot({path:output+'preview-mobile.png',scale:'css'});
    await page.locator('#pane-report [data-evidence]').first().click();
    assert(await page.locator('#drawer').isVisible(),'mobile drawer');
    const box=await page.locator('#drawer').boundingBox();
    assert(box.x>=0&&box.x+box.width<=391,'mobile drawer width');
    await page.screenshot({path:output+'verification/evidence-mobile.png',scale:'css'});
    await page.keyboard.press('Escape');
    await page.setViewportSize({width:1440,height:1100});
    await page.locator('#diagnosis-title').click();
    await page.evaluate(()=>window.scrollTo(0,0));
    await page.screenshot({path:output+'preview.png',scale:'css'});
    await page.locator('#tab-candidates').click();
    await page.screenshot({path:output+'verification/candidates-desktop.png',scale:'css'});
    await page.locator('#tab-report').click();
  });
  await check('直接打开 HTML 文件可导航并读取静态清单', async () => {
    await page.goto('file:///D:/ragPdfSystem++agent/docs/prototypes/aiops-v1/index.html');
    assert((await text('#pane-report')).includes('confirmed_cause'),'file default report');
    await nav('history');
    assert(await page.locator('#history-body tr').count()===3,'file history');
    await nav('interfaces');
    assert(await page.locator('#api-body [data-api]').count()===78,'file contracts');
    await page.goto(base);
  });
  await check('运行时与网络边界', async () => {
    assert(errors.length===0,'console/page errors '+JSON.stringify(errors));
    assert(badResponses.length===0,'http errors '+JSON.stringify(badResponses));
    const external=requests.filter(r=>!r.url.startsWith(base)&&!r.url.startsWith('file:///D:/ragPdfSystem++agent/docs/prototypes/aiops-v1/')&&!r.url.startsWith('blob:')&&!r.url.startsWith('data:'));
    assert(external.length===0,'external requests '+JSON.stringify(external));
    assert(requests.every(r=>r.method==='GET'),'non-GET network request');
    assert(requests.every(r=>!r.url.includes('/api/v1/')),'product API request');
  });
  return {date:'2026-11-13',checks:results,passed:results.filter(r=>r.status==='passed').length,failed:results.filter(r=>r.status==='failed').length,errors,badResponses,requests,scope:'fictional local prototype; no product API or model calls'};
}
