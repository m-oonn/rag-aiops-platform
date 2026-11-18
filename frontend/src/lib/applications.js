export const assistantFields = [
  "name",
  "description",
  "llm_model",
  "temperature",
  "system_prompt",
  "greeting_message",
  "memory_config",
  "kb_ids",
  "rag_config",
  "tool_config",
  "agent_ids",
];
export function assistantConfig(row) {
  return Object.fromEntries(
    assistantFields
      .filter((key) => row[key] !== undefined)
      .map((key) => [key, row[key]]),
  );
}
export function applicationBody(form, original = {}, isAgent = false) {
  const common = {
    name: form.name.trim(),
    description: form.description.trim() || null,
    system_prompt: form.system_prompt || null,
  };
  const memory = { ...original.memory_config, ...form.memory_config };
  if (!isAgent)
    return {
      ...assistantConfig(original),
      ...common,
      ...(form.llm_model ? { llm_model: form.llm_model } : {}),
      temperature: Number(form.temperature),
      greeting_message: form.greeting_message || null,
      memory_config: memory,
      kb_ids: form.knowledge_config.kb_ids.map(Number),
      rag_config: {
        ...original.rag_config,
        top_k: Number(form.knowledge_config.top_k),
      },
      agent_ids: form.agent_ids.map(Number),
    };
  return {
    ...common,
    type: form.type,
    tools_config: Object.fromEntries(
      form.toolRows.map((tool) => [
        tool.name.trim(),
        { transport: tool.transport, url: tool.url.trim() },
      ]),
    ),
    knowledge_config: {
      ...original.knowledge_config,
      ...form.knowledge_config,
    },
    memory_config: memory,
    llm_config: {
      ...original.llm_config,
      model: form.llm_model || null,
      temperature: Number(form.temperature),
      max_tokens: Number(form.max_tokens),
      top_p: Number(form.top_p),
    },
    execution_config: {
      ...original.execution_config,
      ...form.execution_config,
    },
    // Fields without an editor keep their saved values on update.
    ...(original.config != null ? { config: original.config } : {}),
  };
}
