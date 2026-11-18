import { describe, expect, it } from "vitest";
import { applicationBody, assistantConfig } from "./applications";

const form = () => ({
  name: "值班助手",
  description: "服务排查",
  system_prompt: "依据证据回答",
  greeting_message: "需要排查什么？",
  llm_model: "",
  temperature: 0.7,
  knowledge_config: { kb_ids: [1], top_k: 5 },
  memory_config: { enable_short_term: true, window_size: 10 },
  agent_ids: [6],
  toolRows: [],
  execution_config: { max_iterations: 5 },
  type: "function_call",
  max_tokens: 2048,
  top_p: 1,
});

describe("application configuration updates", () => {
  it("preserves assistant tools and unedited retrieval and memory settings", () => {
    const original = {
      id: 3,
      llm_model: "saved-model",
      tool_config: ["existing-tool"],
      rag_config: { enable_rerank: false, top_k: 8 },
      memory_config: { custom_setting: true },
      greeting_message: "原欢迎语",
    };
    const body = applicationBody(form(), original);
    expect(body).toMatchObject({
      llm_model: "saved-model",
      tool_config: ["existing-tool"],
      agent_ids: [6],
      greeting_message: "需要排查什么？",
      description: "服务排查",
      rag_config: { enable_rerank: false, top_k: 5 },
      memory_config: { custom_setting: true },
    });
    expect(body).not.toHaveProperty("id");
  });

  it("uses the server default model for new assistants and excludes record metadata from restored versions", () => {
    expect(applicationBody(form())).not.toHaveProperty("llm_model");
    expect(
      assistantConfig({
        id: 4,
        created_at: "2026-11-13",
        name: "旧版本",
        tool_config: ["tool"],
      }),
    ).toEqual({ name: "旧版本", tool_config: ["tool"] });
  });

  it("retains agent configuration that has no editor and merges editable nested settings", () => {
    const body = applicationBody(
      form(),
      {
        config: { saved: true },
        knowledge_config: { custom: "keep" },
        execution_config: { tool_timeout: 77 },
        security_config: { allow_internet: false },
      },
      true,
    );
    expect(body).toMatchObject({
      config: { saved: true },
      knowledge_config: { custom: "keep", kb_ids: [1] },
      execution_config: { tool_timeout: 77, max_iterations: 5 },
    });
    expect(body).not.toHaveProperty("security_config");
  });
});
