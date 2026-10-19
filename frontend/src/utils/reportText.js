// 报告文本净化：把后端"关键证据"里直出的工具原始返回（形如
// `[{"type":"text","text":"..."}]` 的 ToolMessage 数组）提取成可读文本。
// 只做展示层兜底，不改后端报告生成逻辑。

const MARKER = '[{"type"'
const MAX_CANDIDATE = 20000

function tryParseToolArray(candidate) {
  try {
    const parsed = JSON.parse(candidate)
    if (!Array.isArray(parsed) || !parsed.length) return null
    if (!parsed.every((item) => item && typeof item === 'object')) return null
    const text = parsed
      .map((item) => (typeof item.text === 'string' ? item.text : ''))
      .filter(Boolean)
      .join('\n')
    return text || null
  } catch (_) {
    return null
  }
}

// 兜底：数组 JSON 被截断成非法片段时（后端旧报告按长度截断的历史数据），
// 从 `"text": "` 起提取到段内最后一个引号，尽力还原可读文本。
function fallbackFromTruncated(out, idx) {
  const seg = out.slice(idx, idx + MAX_CANDIDATE)
  const m = seg.match(/"text"\s*:\s*"((?:\\.|[^"\\])*)/)
  if (!m) return null
  let text
  try {
    text = JSON.parse('"' + m[1] + '"')
  } catch (_) {
    text = m[1].replace(/\\+"/g, '"').replace(/\\\\/g, '\\')
  }
  if (!text.trim()) return null
  return text.length > 400 ? text.slice(0, 400) + '…' : text
}

export function extractToolText(input) {
  if (typeof input !== 'string' || !input.includes(MARKER)) return input ?? ''
  let out = input
  // 每处标记逐一尝试：先取最近的 `}]` 作为候选结尾，解析失败则向后扩展
  // （文本内容里可能自带 `}]` 字样）。扩展到上限仍失败就做截断兜底，
  // 绝不截断正常内容。
  let idx = out.indexOf(MARKER)
  let guard = 0
  while (idx !== -1 && guard < 50) {
    guard += 1
    let end = out.indexOf('}]', idx)
    let replaced = false
    while (end !== -1 && end + 2 - idx <= MAX_CANDIDATE) {
      const text = tryParseToolArray(out.slice(idx, end + 2))
      if (text !== null) {
        out = out.slice(0, idx) + text + out.slice(end + 2)
        replaced = true
        break
      }
      end = out.indexOf('}]', end + 1)
    }
    if (!replaced) {
      const seg = out.slice(idx, idx + MAX_CANDIDATE)
      const m = seg.match(/"text"\s*:\s*"((?:\\.|[^"\\])*)/)
      if (m) {
        const text = fallbackFromTruncated(out, idx)
        if (text !== null) {
          const cut = idx + m.index + m[0].length
          out = out.slice(0, idx) + text + out.slice(cut)
          replaced = true
        }
      }
    }
    if (!replaced) break
    idx = out.indexOf(MARKER, idx)
  }
  return out
}

export default extractToolText
