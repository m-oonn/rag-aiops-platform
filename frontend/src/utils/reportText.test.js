import { describe, it, expect } from 'vitest'
import { extractToolText } from './reportText'

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
    const raw = '前缀 [{"type":"text","text":"未闭合'
    expect(extractToolText(raw)).toBe(raw)
  })

  it('is safe for empty and non-string input', () => {
    expect(extractToolText('')).toBe('')
    expect(extractToolText(undefined)).toBe('')
    expect(extractToolText(null)).toBe('')
  })
})
