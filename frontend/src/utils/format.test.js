import { describe, it, expect } from 'vitest'
import { formatDate, formatDateOnly, formatSize } from './format'

describe('formatDate', () => {
  it('returns empty string for falsy input', () => {
    expect(formatDate('')).toBe('')
    expect(formatDate(null)).toBe('')
    expect(formatDate(undefined)).toBe('')
  })

  it('parses a timestamp without Z as UTC (appends Z)', () => {
    // 补 Z 与显式 Z 应解析为同一时刻
    expect(formatDate('2024-01-01T00:00:00')).toBe(
      formatDate('2024-01-01T00:00:00Z')
    )
  })

  it('produces a non-empty localized string for a valid date', () => {
    expect(formatDate('2024-01-01T00:00:00Z')).not.toBe('')
  })
})

describe('formatDateOnly', () => {
  it('returns empty for falsy input', () => {
    expect(formatDateOnly(null)).toBe('')
  })
  it('normalizes missing Z the same as explicit Z', () => {
    expect(formatDateOnly('2024-06-15T10:00:00')).toBe(
      formatDateOnly('2024-06-15T10:00:00Z')
    )
  })
})

describe('formatSize', () => {
  it('returns 0 B for zero/falsy', () => {
    expect(formatSize(0)).toBe('0 B')
    expect(formatSize(undefined)).toBe('0 B')
  })
  it('formats bytes across units', () => {
    expect(formatSize(500)).toBe('500 B')
    expect(formatSize(1024)).toBe('1 KB')
    expect(formatSize(1536)).toBe('1.5 KB')
    expect(formatSize(1048576)).toBe('1 MB')
    expect(formatSize(1073741824)).toBe('1 GB')
  })
})
