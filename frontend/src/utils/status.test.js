import { describe, it, expect } from 'vitest'
import {
  getNumericStatusType,
  getDocStatusText,
  getEvalStatusText,
  getQueueStatusType,
  getQueueStatusText,
} from './status'

describe('getNumericStatusType', () => {
  it('maps 0-3 to Tag types', () => {
    expect(getNumericStatusType(0)).toBe('info')
    expect(getNumericStatusType(1)).toBe('warning')
    expect(getNumericStatusType(2)).toBe('success')
    expect(getNumericStatusType(3)).toBe('danger')
  })
  it('falls back to info for unknown', () => {
    expect(getNumericStatusType(99)).toBe('info')
    expect(getNumericStatusType(undefined)).toBe('info')
  })
})

describe('getDocStatusText', () => {
  it('maps document statuses', () => {
    expect(getDocStatusText(0)).toBe('上传中')
    expect(getDocStatusText(1)).toBe('处理中')
    expect(getDocStatusText(2)).toBe('已完成')
    expect(getDocStatusText(3)).toBe('失败')
  })
  it('falls back to 未知', () => {
    expect(getDocStatusText(99)).toBe('未知')
  })
})

describe('getEvalStatusText', () => {
  it('maps evaluation statuses', () => {
    expect(getEvalStatusText(0)).toBe('待处理')
    expect(getEvalStatusText(1)).toBe('运行中')
    expect(getEvalStatusText(2)).toBe('已完成')
    expect(getEvalStatusText(3)).toBe('失败')
  })
  it('falls back to 未知', () => {
    expect(getEvalStatusText(99)).toBe('未知')
  })
})

describe('queue status helpers', () => {
  it('maps queue status to Tag types', () => {
    expect(getQueueStatusType('SUCCESS')).toBe('success')
    expect(getQueueStatusType('FAILURE')).toBe('danger')
    expect(getQueueStatusType('PROCESSING')).toBe('warning')
    expect(getQueueStatusType('PENDING')).toBe('info')
    expect(getQueueStatusType('WHATEVER')).toBe('info')
  })
  it('maps queue status to text, passing through unknown', () => {
    expect(getQueueStatusText('PENDING')).toBe('待处理')
    expect(getQueueStatusText('PROCESSING')).toBe('处理中')
    expect(getQueueStatusText('SUCCESS')).toBe('成功')
    expect(getQueueStatusText('FAILURE')).toBe('失败')
    expect(getQueueStatusText('CUSTOM')).toBe('CUSTOM')
  })
})
