import { describe, it, expect } from 'vitest'
import { extractToolText, summarizeJsonObject, polishReportText } from './reportText'

describe('extractToolText', () => {
  it('extracts text from a single ToolMessage array', () => {
    const raw = '**验证 外部依赖故障**: [{"type": "text", "text": "1792392816764", "id": "lc_abc"}]'
    expect(extractToolText(raw)).toBe('**验证 外部依赖故障**: 1792392816764')
  })

  it('joins multiple text items and drops non-text fields', () => {
    const raw = '[{"type":"text","text":"第一段"},{"type":"text","text":"第二段"},{"id":"x"}]'
    expect(extractToolText(raw)).toBe('第一段\n第二段')
  })

  it('unwraps when content itself contains closing brackets', () => {
    const raw = '[{"type":"text","text":"{\\"total\\":0,\\"logs\\":[]}"}]'
    expect(extractToolText(raw)).toBe('{"total":0,"logs":[]}')
  })

  it('leaves plain report text untouched', () => {
    const text = '# 诊断结果\n\n## 结论\n最可能的根因是应用层异常。'
    expect(extractToolText(text)).toBe(text)
  })

  it('keeps original text when the marker never closes', () => {
    const raw = '前缀 [{"type":"text","未闭合'
    expect(extractToolText(raw)).toBe(raw)
  })

  it('salvages readable text from a truncated tool array (legacy reports)', () => {
    const raw = '- **查日志**: [{"type": "text", "text": "{\\"topic_id\\":\\"order-logs\\",\\"total\\":0,\\"lo'
    const out = extractToolText(raw)
    expect(out).toContain('{\"topic_id\":\"order-logs\"')
    expect(out).not.toContain('[{\"type\"')
  })

  it('is safe for empty and non-string input', () => {
    expect(extractToolText('')).toBe('')
    expect(extractToolText(undefined)).toBe('')
    expect(extractToolText(null)).toBe('')
  })

  it('summarizes known search_log objects into one readable line', () => {
    const line = summarizeJsonObject({
      topic_id: 'order-service-logs-2026.10.13', start_time: 1792391024522, end_time: 1792398224522,
      query: '*', limit: 50, total: 0, logs: [], data_source: 'elasticsearch', message: 'ok',
    })
    expect(line).toContain('日志检索 order-service-logs-2026.10.13（数据源 elasticsearch）：命中 0 条')
    expect(line).toContain('窗口内无日志记录')
    expect(line).toContain('；ok')
  })

  it('returns null for unknown JSON shapes', () => {
    expect(summarizeJsonObject({ foo: { bar: 1 } })).toBeNull()
  })

  it('salvages truncated tool arrays into a readable summary (legacy backend)', () => {
    const raw = '- **验证 外部依赖故障**: [{"type": "text", "text": "{\\"topic_id\\":\\"order-logs\\",\\"start_time\\":1792391024522,\\"total\\":0,\\"logs\\":[],\\"data_source\\":\\"elasticsearch\\"'
    const out = extractToolText(raw)
    expect(out).toContain('日志检索 order-logs（数据源 elasticsearch）：命中 0 条')
    expect(out).not.toContain('[{"type"')
  })

  it('polishReportText strips heading marks and cuts raw tables in bullets', () => {
    const raw = '- **先确认变更**: ## 诊断结果：变更时间对齐 ### 1. 变更查询结果| 查询窗口| 服务| 命中数| 最近 1 小时| order| 0\n\n| 保留列 | 正常列 |\n|---|---|\n| a | b |'
    const out = polishReportText(raw)
    expect(out).not.toContain('## ')
    const bullet = out.split('\n')[0]
    expect(bullet).toContain('…')
    expect(bullet).not.toContain('|')
    expect(out).toContain('| 保留列 | 正常列 |')
  })
})
