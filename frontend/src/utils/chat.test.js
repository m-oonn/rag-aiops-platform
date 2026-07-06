import { describe, it, expect } from 'vitest'
import { getChatStreamUrl, renderMarkdown } from './chat'

describe('getChatStreamUrl', () => {
  it('returns relative API URL instead of hardcoded localhost', () => {
    const url = getChatStreamUrl()
    expect(url).toBe('/api/v1/chat/stream')
    expect(url).not.toContain('localhost')
    expect(url).not.toContain('8200')
  })
})

describe('renderMarkdown', () => {
  it('renders basic markdown to HTML', () => {
    expect(renderMarkdown('**bold**')).toContain('<strong>bold</strong>')
  })

  it('strips script tags to prevent XSS', () => {
    const html = renderMarkdown('<script>alert(1)</script>')
    expect(html).not.toContain('<script')
  })

  it('strips inline event handlers to prevent XSS', () => {
    const html = renderMarkdown('<img src="x" onerror="alert(1)">')
    expect(html).not.toContain('onerror')
  })

  it('returns empty string for empty input', () => {
    expect(renderMarkdown('')).toBe('')
    expect(renderMarkdown(null)).toBe('')
  })
})
