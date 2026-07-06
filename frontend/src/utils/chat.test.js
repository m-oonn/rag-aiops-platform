import { describe, it, expect } from 'vitest'
import { getChatStreamUrl } from './chat'

describe('getChatStreamUrl', () => {
  it('returns relative API URL instead of hardcoded localhost', () => {
    const url = getChatStreamUrl()
    expect(url).toBe('/api/v1/chat/stream')
    expect(url).not.toContain('localhost')
    expect(url).not.toContain('8200')
  })
})
