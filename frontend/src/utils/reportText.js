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

// ── 已知 MCP 输出形态 → 一句人话摘要（与后端 report_text.py 对齐） ──
function fmtTs(ms) {
  const n = Number(ms)
  if (!Number.isFinite(n) || n <= 0) return ''
  try {
    const d = new Date(n)
    const p = (x) => String(x).padStart(2, '0')
    return `${p(d.getHours())}:${p(d.getMinutes())}`
  } catch (_) {
    return ''
  }
}

export function summarizeJsonObject(obj) {
  if (!obj || typeof obj !== 'object' || Array.isArray(obj)) return null
  const ds = typeof obj.data_source === 'string' && obj.data_source ? `（数据源 ${obj.data_source}）` : ''
  const tail = () => (typeof obj.message === 'string' && obj.message.trim() ? `；${obj.message.trim().slice(0, 80)}` : '')
  if ('topic_id' in obj && 'logs' in obj) {
    let line = `日志检索 ${obj.topic_id}${ds}：命中 ${obj.total ?? '?'} 条`
    const st = fmtTs(obj.start_time)
    const et = fmtTs(obj.end_time)
    if (st && et) line += `（窗口 ${st}–${et}）`
    if (typeof obj.query === 'string' && obj.query.trim() && obj.query !== '*') line += `，条件「${obj.query.slice(0, 60)}」`
    if (!Array.isArray(obj.logs) || !obj.logs.length) line += '，窗口内无日志记录'
    return line + tail()
  }
  if ('changes' in obj && 'service_name' in obj) {
    let line = `变更检索 service=${obj.service_name}${ds}：命中 ${obj.total ?? '?'} 条`
    const st = fmtTs(obj.start_time)
    const et = fmtTs(obj.end_time)
    if (st && et) line += `（窗口 ${st}–${et}）`
    if (!Array.isArray(obj.changes) || !obj.changes.length) line += '，窗口内无变更记录'
    return line + tail()
  }
  if ('topics' in obj) {
    const topics = Array.isArray(obj.topics) ? obj.topics : []
    const names = topics.slice(0, 5)
      .map((t) => (t && typeof t === 'object' ? String(t.topic_name || t.topic_id || '') : ''))
      .filter(Boolean)
    let line = `日志主题检索${ds}：命中 ${topics.length} 个`
    if (names.length) line += '：' + names.join('、')
    return line + tail()
  }
  return null
}

function trySummarizeText(text) {
  const s = String(text).trim()
  if (s.startsWith('{') && s.endsWith('}')) {
    try {
      const line = summarizeJsonObject(JSON.parse(s))
      if (line) return line
    } catch (_) { /* 非完整 JSON，走碎片摘要 */ }
  }
  return null
}

// 旧后端把数组截成非法片段时，按已知字段用正则还原摘要
const RE_TOPIC_ID = /"topic_id"\s*:\s*"([^"]*)"/
const RE_SERVICE = /"service_name"\s*:\s*"([^"]*)"/
const RE_TOTAL = /"total"\s*:\s*(\d+)/
const RE_DS = /"data_source"\s*:\s*"([^"]*)"/
const RE_MESSAGE = /"message"\s*:\s*"((?:\\.|[^"\\])*)"/
const RE_LOGS_EMPTY = /"logs"\s*:\s*\[\s*\]/
const RE_CHANGES_EMPTY = /"changes"\s*:\s*\[\s*\]/

function summarizeFragment(frag) {
  const get = (re) => {
    const m = frag.match(re)
    return m ? m[1] : undefined
  }
  const ds = get(RE_DS)
  const tag = ds ? `（数据源 ${ds}）` : ''
  const msgM = frag.match(RE_MESSAGE)
  const tail = msgM ? `；${msgM[1].replace(/\\"/g, '"').slice(0, 80)}` : ''
  const total = get(RE_TOTAL) ?? '?'
  if (frag.includes('"logs"') && frag.includes('"topic_id"')) {
    let line = `日志检索 ${get(RE_TOPIC_ID) ?? '?'}${tag}：命中 ${total} 条`
    if (RE_LOGS_EMPTY.test(frag)) line += '，窗口内无日志记录'
    return line + tail
  }
  if (frag.includes('"changes"') && frag.includes('"service_name"')) {
    let line = `变更检索 service=${get(RE_SERVICE) ?? '?'}${tag}：命中 ${total} 条`
    if (RE_CHANGES_EMPTY.test(frag)) line += '，窗口内无变更记录'
    return line + tail
  }
  return null
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
        out = out.slice(0, idx) + (trySummarizeText(text) ?? text) + out.slice(end + 2)
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
          const summary = trySummarizeText(text) ?? summarizeFragment(text)
          const cut = idx + m.index + m[0].length
          out = out.slice(0, idx) + (summary ?? text) + out.slice(cut)
          replaced = true
        }
      }
    }
    if (!replaced) break
    idx = out.indexOf(MARKER, idx)
  }
  return out
}

// 报告行级清洗：剥掉步骤摘要里被压成一行的 Markdown 标题井号，
// 在原始表格管道处截断（表格明细不适合塞进一行摘要）。只处理
// "- **步骤**: 内容" 形态的列表行，不动报告正文里的正常表格。
export function polishReportText(input) {
  const out = extractToolText(input)
  return out.split('\n').map((line) => {
    const m = line.match(/^(\s*-\s+\*\*[^*]+\*\*:)\s*(.*)$/)
    if (!m) return line
    let content = m[2].replace(/#{1,6}\s*/g, '')
    const pipe = content.indexOf('|')
    if (pipe > 0) content = content.slice(0, pipe).replace(/[；;，,\s]+$/, '') + '…'
    else if (pipe === 0) {
      content = content.split('|')
        .map((s) => s.trim())
        .filter((s) => s && s.replace(/-/g, '') !== '')
        .join('；')
    }
    return `${m[1]} ${content}`
  }).join('\n')
}

export default extractToolText
