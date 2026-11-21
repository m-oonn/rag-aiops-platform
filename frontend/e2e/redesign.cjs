async (page) => {
  const base = "http://127.0.0.1:5275";
  const errors = [],
    unexpected = [],
    writes = [],
    bodies = [];
  let runMode = "normal",
    role = "admin",
    queueFailure = false,
    chatCreateFailure = false;
  const check = (condition, message) => {
    if (!condition) errors.push(message);
  };
  const kb = {
    id: 1,
    kb_uid: "kb-1",
    name: "运行手册",
    description: "线上服务知识库",
    is_public: false,
    owner_id: 7,
    created_at: "2026-11-13T08:00:00Z",
    chunking_config: {
      method: "recursive",
      chunk_size: 800,
      chunk_overlap: 100,
      retrieval_mode: "hybrid",
    },
  };
  const doc = {
    id: 2,
    filename: "故障排查.pdf",
    status: 2,
    file_size: 1572864,
    chunk_count: 14,
    doc_uid: "doc-2",
    created_at: "2026-11-13T09:00:00Z",
  };
  const session = {
    id: 5,
    session_uid: "session-5",
    title: "服务超时怎么排查",
    created_at: "2026-11-13T09:30:00Z",
    assistant_id: null,
  };
  const evaluation = {
    id: 4,
    name: "运行手册评测",
    status: 4,
    total_count: 3,
    completed_count: 3,
    created_at: "2026-11-13T10:00:00Z",
    dataset_path: null,
    is_custom_dataset: false,
  };
  const assistant = {
    id: 3,
    name: "值班助手",
    description: "平台支持",
    greeting_message: "今天需要排查什么？",
    llm_model: "demo",
    temperature: 0.6,
    kb_ids: [1],
    agent_ids: [6],
    tool_config: ["saved-tool"],
    rag_config: { top_k: 8, enable_rerank: false },
    memory_config: {
      enable_short_term: true,
      window_size: 12,
      preserved: true,
    },
    created_at: session.created_at,
  };
  const agent = {
    id: 6,
    name: "日志助手",
    description: "服务问题排查",
    type: "function_call",
    config: { saved: true },
    tools_config: {
      logs: { url: "https://example.test/mcp", transport: "sse" },
    },
    execution_config: { max_iterations: 7, tool_timeout: 45 },
    created_at: session.created_at,
  };
  const evidenceId = "ev-0123456789abcdef";
  const investigation = {
    candidates: [
      {
        id: "h-1",
        explanation: "上游服务连接失败",
        status: "supported",
        evidence_ids: [evidenceId],
      },
    ],
  };
  const user = {
    id: 7,
    username: "operator",
    email: "operator@example.test",
    role: "admin",
    is_active: true,
  };
  const diagnosis = {
    kind: "confirmed_cause",
    conclusion: "上游服务未响应",
    target_id: "service-api",
    evidence: [],
  };
  const sse = [
    {
      type: "plan",
      thread_id: "browser-run-1",
      plan: ["检查 API 日志", "检查上游服务状态"],
    },
    { type: "step_complete", message: "API 日志已读取" },
    {
      type: "report",
      report: "## 诊断结论\n上游服务未响应。[ev-0123456789abcdef]",
      diagnosis,
    },
    {
      type: "complete",
      thread_id: "browser-run-1",
      response: "## 诊断结论\n上游服务未响应。",
      diagnosis,
    },
    {
      type: "usage",
      llm_calls: 1,
      input_tokens: 42,
      output_tokens: 18,
      elapsed_s: 1.4,
    },
  ]
    .map((event) => `data: ${JSON.stringify(event)}\r\n\r\n`)
    .join("");

  page.on("pageerror", (error) => errors.push(error.message));
  page.on("console", (message) => {
    if (message.type() === "error" && !message.text().startsWith("Failed to load resource:"))
      errors.push(message.text());
  });
  await page.route("**/api/v1/**", async (route) => {
    const request = route.request();
    const path =
      request
        .url()
        .replace(/^https?:\/\/[^/]+\/api\/v1/, "")
        .split("?")[0]
        .replace(/\/$/, "") || "/";
    const method = request.method();
    const respond = (body) =>
      route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify(body),
      });
    if (method !== "GET") {
      writes.push(`${method} ${path}`);
      if (request.headers()["content-type"]?.includes("application/json"))
        bodies.push({
          path,
          method,
          body: JSON.parse(request.postData() || "null"),
        });
    }
    if (path === "/auth/me") return respond({ ...user, role });
    if (path === "/auth/users" && method === "GET") return respond([user]);
    if (path === "/knowledge-bases" && method === "GET") return respond([kb]);
    if (path === "/knowledge-bases" && method === "POST")
      return respond({
        ...kb,
        id: 2,
        name: JSON.parse(request.postData()).name,
      });
    if (path === "/knowledge-bases/1" && method === "GET") return respond(kb);
    if (path === "/knowledge-bases/1/documents") return respond([doc]);
    if (path === "/knowledge-bases/documents/2/qa-pairs") return respond([]);
    if (path === "/knowledge-bases/documents/2/chunks")
      return respond({ chunks: [] });
    if (path === "/assistants") return respond([assistant]);
    if (path === "/agents") return respond([agent]);
    if (path === "/assistants/3" && method === "PUT")
      return respond({ ...assistant, ...JSON.parse(request.postData()) });
    if (path === "/agents/6" && method === "PUT")
      return respond({ ...agent, ...JSON.parse(request.postData()) });
    if (path === "/assistants/3/versions")
      return respond([
        {
          version: "v1.0.0",
          config: assistant,
          created_at: session.created_at,
        },
      ]);
    if (path === "/health/models")
      return respond({
        models: [{ id: "demo", name: "演示模型" }],
        default_model: "demo",
      });
    if (path === "/health/dependencies")
      return respond({
        overall: "ok",
        services: {
          llm: { status: "ok" },
          probe: { status: "ok" },
          redis: { status: "ok" },
        },
      });
    if (path === "/health/queues" && queueFailure)
      return route.fulfill({
        status: 503,
        contentType: "application/json",
        body: JSON.stringify({ detail: "任务队列连接失败" }),
      });
    if (path === "/health/queues")
      return respond({
        status: "ok",
        summary: {
          active_tasks: 1,
          reserved_tasks: 2,
          scheduled_tasks: 0,
          workers: 1,
        },
        details: { active: {}, reserved: {}, scheduled: {}, worker_stats: {} },
      });
    if (path === "/health") return respond({ status: "ok", version: "1.0.0" });
    if (path === "/monitor/stats")
      return respond({
        total_pending: 2,
        total_processing: 1,
        total_failed: 0,
        total_completed: 5,
      });
    if (path === "/monitor")
      return respond([
        {
          task_id: "791e8a7d-30e3-4a19-9f02-58ed00be3eb6",
          doc_id: 2,
          filename: doc.filename,
          kb_name: kb.name,
          status: "SUCCESS",
          progress: 100,
          message: null,
          created_at: doc.created_at,
        },
      ]);
    if (path === "/monitor/tasks/2" && method === "DELETE")
      return respond({ message: "Deleted" });
    if (path === "/monitor/tasks/batch-delete" && method === "POST")
      return respond({ message: "Deleted 1 tasks" });
    if (
      path ===
      "/storage/preview/user_7%2F%E6%95%85%E9%9A%9C%E6%8E%92%E6%9F%A5.pdf"
    )
      return route.fulfill({
        contentType: "text/html",
        body: "<h2>文档内容</h2><script>window.previewUnsafe=true</script><img src=x onerror=alert(1)>",
      });
    if (path === "/evaluations/tasks") return respond([evaluation]);
    if (path === "/evaluations/4/dataset")
      return respond([
        {
          id: 10,
          question: "服务超时原因是什么？",
          ground_truth: "依赖服务响应超时",
          qa_type: "single_hop",
        },
      ]);
    if (path === "/evaluations/4/upload-dataset" && method === "POST")
      return respond({ message: "Uploaded 1 items" });
    if (path === "/evaluations/4/report")
      return respond({ content: "# 评测结果\n召回率 0.92" });
    if (path === "/storage/files")
      return respond({
        files: [
          {
            object_name: "user_7/故障排查.pdf",
            size: 1024,
            last_modified: doc.created_at,
          },
        ],
      });
    if (path === "/chat/sessions" && method === "GET")
      return respond([session]);
    if (path === "/chat/sessions" && method === "POST") {
      if (chatCreateFailure)
        return route.fulfill({
          status: 500,
          contentType: "application/json",
          body: JSON.stringify({ detail: "创建会话失败" }),
        });
      return respond(session);
    }
    if (path === "/chat/sessions/session-5/messages")
      return respond([
        {
          query: "服务超时怎么排查？",
          answer: "先检查依赖服务状态。",
          created_at: session.created_at,
        },
      ]);
    if (path === "/chat" && method === "POST")
      return respond({
        session_id: "session-5",
        query: "你好",
        answer: "你好，有什么可以协助？",
        source_documents: [
          {
            text: "运行手册中的排查步骤",
            metadata: { filename: "故障排查.pdf" },
            score: 0.92,
          },
        ],
      });
    if (path === "/aiops" && method === "POST")
      return route.fulfill({
        status: 200,
        contentType: "text/event-stream",
        body:
          runMode === "normal"
            ? sse
            : [
                {
                  type: "plan",
                  thread_id: "browser-run-1",
                  plan: ["检查 API 日志"],
                },
                ...(runMode === "approval"
                  ? [
                      {
                        type: "pending_terminal_approval",
                        termcp_ui_url: "http://127.0.0.1:9000/approval",
                        command: "Get-Service",
                      },
                    ]
                  : []),
              ]
                .map((event) => `data: ${JSON.stringify(event)}\r\n\r\n`)
                .join(""),
      });
    if (path === "/aiops/runs/browser-run-1/continue")
      return route.fulfill({
        status: 409,
        contentType: "application/json",
        body: JSON.stringify({ detail: "命令尚未审批" }),
      });
    if (path === "/aiops/runs/browser-run-1")
      return respond({
        thread_id: "browser-run-1",
        status: runMode === "approval" ? "pending_terminal" : "completed",
        report: "## 诊断结论\n上游服务未响应。",
        diagnosis,
        terminal_approval:
          runMode === "approval" ? { command: "Get-Service" } : null,
        termcp_ui_url:
          runMode === "approval" ? "http://127.0.0.1:9000/approval" : "",
        investigation,
        evidence: [],
        steps: [],
      });
    if (path === "/aiops/runs/browser-run-1/evidence")
      return respond({
        evidence: [
          {
            evidence_id: evidenceId,
            kind: "日志",
            summary: "上游连接超时",
            target_id: "service-api",
            raw_available: true,
          },
        ],
        total: 1,
        can_read_raw: true,
      });
    if (path === "/aiops/runs/browser-run-1/steps")
      return respond({
        steps:
          runMode === "approval"
            ? []
            : [
                {
                  node: "planner",
                  payload: { plan: ["检查 API 日志", "检查上游服务状态"] },
                },
                {
                  node: "executor",
                  payload: {
                    last_step: "检查 API 日志",
                    result_digest: "上游连接超时",
                  },
                },
              ],
        total: 2,
      });
    if (path.startsWith("/aiops/runs/browser-run-1/evidence/"))
      return respond({
        evidence_id: path.split("/").at(-1),
        summary: "上游服务连接失败",
        kind: "日志",
        ...(role === "admin"
          ? { raw: { observation: "连接失败", redacted: true } }
          : {}),
        raw_ref: "SERVER_PRIVATE_PATH",
      });
    unexpected.push(`${method} ${path}`);
    return route.fulfill({
      status: 404,
      contentType: "application/json",
      body: JSON.stringify({ detail: `未模拟接口 ${method} ${path}` }),
    });
  });

  await page.goto(`${base}/login`);
  await page.evaluate(() => {
    localStorage.setItem("token", "browser-test");
    localStorage.setItem("role", "admin");
  });
  await page.setViewportSize({ width: 1440, height: 1000 });
  const routes = [
    "/dashboard",
    "/aiops",
    "/aiops/history",
    "/chat",
    "/knowledge-bases",
    "/knowledge-bases/1",
    "/assistants",
    "/agents",
    "/evaluation",
    "/monitor",
    "/storage",
    "/platform",
    "/users",
  ];
  const pages = [];
  for (const path of routes) {
    await page.goto(`${base}${path}`);
    await page.locator(".app-main > *").first().waitFor();
    await page.waitForTimeout(100);
    const measurement = await page.evaluate(() => ({
      viewport: innerWidth,
      body: document.documentElement.scrollWidth,
      title: document.querySelector("h1")?.textContent?.trim(),
    }));
    pages.push({ path, ...measurement });
    if (measurement.body > measurement.viewport + 1)
      errors.push(`${path}: desktop overflow ${measurement.body}`);
  }

  await page.goto(`${base}/knowledge-bases`);
  await page.getByRole("button", { name: "新建知识库" }).click();
  await page.getByRole("textbox", { name: "名称" }).fill("发布检查清单");
  await page.getByRole("button", { name: "保存知识库" }).click();
  await page.getByText("知识库已创建").waitFor();
  if (!writes.includes("POST /knowledge-bases"))
    errors.push("Knowledge base creation did not call the API");

  await page.goto(`${base}/aiops`);
  await page
    .getByLabel("故障现象")
    .fill("订单 API 返回 503，依赖服务连接超时。");
  await page.getByRole("button", { name: "开始诊断" }).click();
  await page.getByText("上游服务未响应").first().waitFor();
  await page.getByRole("tab", { name: /排查过程/ }).click();
  await page.getByText(/排查计划 ·/).click();
  await page.getByText("检查 API 日志").waitFor();

  await page.getByRole("tab", { name: /候选原因/ }).click();
  await page.getByText("上游服务连接失败", { exact: true }).waitFor();
  await page.getByRole("tab", { name: /现场证据/ }).click();
  await page.getByRole("button", { name: /上游连接超时/ }).click();
  await page.getByRole("button", { name: "来源与原文" }).click();
  await page.getByRole("button", { name: "读取现场原文" }).click();
  await page.getByText(/"redacted": true/).waitFor();
  check(
    !(await page.locator("body").innerText()).includes("SERVER_PRIVATE_PATH"),
    "Evidence exposes a server path",
  );
  await page.getByRole("button", { name: "关闭此对话框" }).click();
  await page.getByRole("tab", { name: /诊断报告/ }).click();
  await page.screenshot({
    path: "runtime/frontend-redesign-20261113/diagnosis.png",
    fullPage: true,
  });

  await page.goto(`${base}/knowledge-bases/1`);
  await page
    .locator('nav[aria-label="知识库内容"]')
    .getByRole("button", { name: /^问答对/ })
    .click();
  await page.getByText("暂无问答对", { exact: true }).waitFor();
  await page.getByRole("button", { name: "知识检索", exact: true }).click();
  await page.getByLabel("知识检索关键词").fill("服务超时如何排查");
  await page.getByRole("button", { name: "查询", exact: true }).click();
  await page.getByText("你好，有什么可以协助？", { exact: true }).waitFor();
  await page.getByText("运行手册中的排查步骤", { exact: true }).waitFor();
  await page.getByRole("button", { name: "设置", exact: true }).click();
  await page.getByRole("link", { name: "编辑知识库" }).click();
  await page.getByRole("dialog", { name: "编辑知识库" }).waitFor();
  await page.getByRole("button", { name: "取消", exact: true }).click();
  await page.goto(`${base}/knowledge-bases/1`);
  await page.getByRole("heading", { name: "运行手册", exact: true }).waitFor();
  await page.screenshot({
    path: "runtime/frontend-redesign-20261113/knowledge.png",
    fullPage: true,
  });

  await page.goto(`${base}/monitor`);
  await page.getByRole("button", { name: "删除", exact: true }).click();
  await page.getByRole("button", { name: "删除", exact: true }).last().click();
  await page.getByText("任务已删除", { exact: true }).waitFor();
  await page
    .getByRole("checkbox", { name: "选择 故障排查.pdf", exact: true })
    .check();
  await page.getByRole("button", { name: "删除 1 项" }).click();
  await page.getByRole("button", { name: "删除", exact: true }).last().click();
  await page.waitForTimeout(100);
  check(
    writes.includes("DELETE /monitor/tasks/2"),
    "Task deletion used the Celery UUID instead of document ID",
  );
  check(
    bodies.some(
      (row) =>
        row.path === "/monitor/tasks/batch-delete" &&
        row.body.task_ids[0] === "2",
    ),
    "Task selection did not send document IDs",
  );

  await page.goto(`${base}/assistants`);
  await page.getByRole("button", { name: "编辑", exact: true }).click();
  await page.getByLabel("描述", { exact: true }).fill("已更新的描述");
  await page.getByRole("button", { name: "保存", exact: true }).click();
  await page.getByText("助手已保存", { exact: true }).waitFor();
  const saved = bodies.find(
    (row) => row.method === "PUT" && row.path === "/assistants/3",
  )?.body;
  check(
    saved?.tool_config?.[0] === "saved-tool" &&
      saved?.agent_ids?.[0] === 6 &&
      saved?.greeting_message === assistant.greeting_message &&
      saved?.rag_config?.enable_rerank === false,
    "Assistant edit lost existing configuration",
  );
  await page.getByRole("button", { name: "历史版本", exact: true }).click();
  await page.getByText("v1.0.0", { exact: true }).waitFor();
  await page.getByRole("button", { name: "关闭此对话框" }).click();
  await page.goto(`${base}/agents`);
  await page.getByRole("button", { name: "编辑", exact: true }).click();
  await page.getByLabel("描述", { exact: true }).fill("更新日志工具");
  await page.getByRole("button", { name: "保存", exact: true }).click();
  await page.getByText("智能体已保存", { exact: true }).waitFor();
  const savedAgent = bodies.find(
    (row) => row.method === "PUT" && row.path === "/agents/6",
  )?.body;
  check(
    savedAgent?.config?.saved === true &&
      savedAgent?.tools_config?.logs?.transport === "sse" &&
      savedAgent?.execution_config?.tool_timeout === 45,
    "Agent edit lost saved configuration",
  );

  await page.goto(`${base}/evaluation`);
  await page.getByRole("button", { name: "数据集", exact: true }).click();
  await page.getByRole("button", { name: "上传数据集", exact: true }).click();
  await page.getByLabel("数据集文件").evaluate((input) => {
    const transfer = new DataTransfer();
    transfer.items.add(
      new File(["[]"], "additional.json", { type: "application/json" }),
    );
    input.files = transfer.files;
    input.dispatchEvent(new Event("change", { bubbles: true }));
  });
  await page
    .getByRole("button", { name: "上传数据集", exact: true })
    .last()
    .click();
  await page.getByRole("button", { name: "上传", exact: true }).click();
  await page.getByText("数据集已上传").waitFor();
  if (!writes.includes("POST /evaluations/4/upload-dataset"))
    errors.push("Dataset upload did not use the selected evaluation task");

  const mobile = [];
  for (const width of [320, 390]) {
    await page.setViewportSize({ width, height: 844 });
    for (const path of routes) {
      await page.goto(`${base}${path}`);
      await page.locator(".app-main > *").first().waitFor();
      const measurement = await page.evaluate(() => ({
        viewport: innerWidth,
        body: document.documentElement.scrollWidth,
      }));
      mobile.push({ width, path, ...measurement });
      if (measurement.body > width + 1)
        errors.push(
          `${path}: mobile overflow at ${width}px (${measurement.body})`,
        );
    }
  }
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto(`${base}/chat`);
  await page.getByRole("button", { name: "打开会话列表" }).click();
  await page.locator(".chat-sessions.open").waitFor();
  await page.getByRole("button", { name: /^服务超时怎么排查/ }).click();
  await page.getByText("先检查依赖服务状态。", { exact: true }).waitFor();
  check(
    !(await page.locator(".chat-sessions").isVisible()),
    "Mobile history does not close after selecting a session",
  );
  await page.screenshot({
    path: "runtime/frontend-redesign-20261113/mobile-chat.png",
    fullPage: true,
  });
  await page.goto(`${base}/dashboard`);
  await page.getByRole("button", { name: "打开导航" }).click();
  await page.getByRole("link", { name: "最近诊断", exact: true }).click();
  await page.waitForURL("**/aiops/history");
  await page.locator(".el-drawer").waitFor({ state: "hidden" });
  await page.goto(`${base}/dashboard`);
  await page.waitForTimeout(100);
  await page.screenshot({
    path: "runtime/frontend-redesign-20261113/mobile.png",
    fullPage: true,
  });
  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.goto(`${base}/dashboard`);
  await page.screenshot({
    path: "runtime/frontend-redesign-20261113/desktop.png",
    fullPage: true,
  });

  await page.goto(`${base}/storage`);
  await page.getByRole("button", { name: "预览", exact: true }).click();
  await page.getByRole("heading", { name: "文档内容" }).waitFor();
  check(
    (await page
      .locator(".el-dialog .markdown script, .el-dialog .markdown img")
      .count()) === 0,
    "File preview contains unsafe HTML",
  );
  check(
    !(await page.evaluate(() => window.previewUnsafe)),
    "File preview executed a script",
  );
  await page.getByRole("button", { name: "关闭此对话框" }).click();

  runMode = "disconnected";
  await page.goto(`${base}/aiops`);
  await page.getByLabel("故障现象").fill("连接中断测试");
  await page.getByRole("button", { name: "开始诊断" }).click();
  await page
    .getByText("连接已结束，正在读取已保存的诊断", { exact: true })
    .waitFor();
  check(
    await page.getByRole("button", { name: "重新载入" }).isVisible(),
    "Incomplete SSE was marked complete",
  );

  runMode = "approval";
  await page.goto(`${base}/aiops`);
  await page.getByLabel("故障现象").fill("命令审批测试");
  await page.getByRole("button", { name: "开始诊断" }).click();
  await page.getByText("终端命令待审批", { exact: true }).waitFor();
  check(
    (await page.getByRole("button", { name: "开始诊断" }).count()) === 0,
    "Paused diagnosis can be resubmitted",
  );
  check(
    (await page
      .getByRole("link", { name: "打开审批页" })
      .getAttribute("href")) === "http://127.0.0.1:9000/approval",
    "Approval does not open the external approval tool",
  );
  await page.getByRole("button", { name: "检查审批并继续" }).click();
  await page
    .locator('[role="alert"]')
    .getByText("命令尚未审批", { exact: true })
    .waitFor();
  check(
    await page.getByText("终端命令待审批", { exact: true }).isVisible(),
    "409 discarded pending approval",
  );
  await page.reload();
  await page.getByText("终端命令待审批", { exact: true }).waitFor();
  await page.getByText("暂无排查步骤", { exact: true }).waitFor();
  check(
    (await page.locator(".diagnosis-output .spinner").count()) === 0,
    "Paused empty steps remain loading",
  );

  queueFailure = true;
  await page.goto(`${base}/platform?tab=queues`);
  await page.getByText("任务队列连接失败", { exact: true }).waitFor();
  queueFailure = false;
  await page.getByRole("button", { name: "重试", exact: true }).click();
  await page.getByText("在线处理节点", { exact: true }).waitFor();
  await page.goto(`${base}/platform?tab=models`);
  await page.getByText("演示模型", { exact: true }).waitFor();

  await page.goto(`${base}/chat`);
  await page.getByRole("button", { name: /^服务超时怎么排查/ }).click();
  await page.getByText("先检查依赖服务状态。", { exact: true }).waitFor();
  await page.getByLabel("输入问题").fill("保留我的问题");
  chatCreateFailure = true;
  await page.getByRole("button", { name: "新建会话", exact: true }).click();
  await page.getByText("创建会话失败", { exact: true }).waitFor();
  check(
    await page.getByText("先检查依赖服务状态。", { exact: true }).isVisible(),
    "Failed new session cleared messages",
  );
  check(
    (await page.getByLabel("输入问题").inputValue()) === "保留我的问题",
    "Failed new session cleared draft",
  );
  await page.getByRole("button", { name: "发送", exact: true }).click();
  await page.getByText("你好，有什么可以协助？", { exact: true }).waitFor();
  await page.getByText("参考资料 · 1", { exact: true }).waitFor();

  role = "user";
  runMode = "normal";
  await page.goto(`${base}/aiops?run=browser-run-1`);
  await page.getByRole("tab", { name: /现场证据/ }).click();
  await page.getByRole("button", { name: /上游连接超时/ }).click();
  await page.getByRole("button", { name: "来源与原文" }).click();
  await page.getByText("上游服务连接失败", { exact: true }).first().waitFor();
  check(
    (await page.getByRole("button", { name: "读取现场原文" }).count()) === 0,
    "Member can open raw evidence",
  );
  check(
    (await page
      .getByRole("link", { name: "用户管理", exact: true })
      .count()) === 0,
    "Member sees admin navigation",
  );
  await page.goto(`${base}/users`);
  await page.waitForURL("**/dashboard");

  return {
    pages,
    mobile,
    writes,
    unexpected,
    errors,
    status: errors.length || unexpected.length ? "failed" : "passed",
  };
}
