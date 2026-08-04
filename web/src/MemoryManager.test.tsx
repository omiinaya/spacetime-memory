import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import MemoryManager from './MemoryManager'

vi.mock('./lib/stdb', () => ({
  stdbSql: vi.fn(),
  stdbQuery: vi.fn(),
  sortDesc: (rows: any[], field: string) =>
    rows.slice().sort((a, b) => String(b[field] ?? '').localeCompare(String(a[field] ?? ''))),
}))

import { stdbQuery, stdbSql } from './lib/stdb'

const workspaces = [
  { id: 'ws-1', name: 'Benchmark bench-31', created_at: 1785830064000 },
]

const memories = [
  {
    id: 'm1',
    content: 'Calvin: thanks!',
    summary: '',
    memory_type: 'experience',
    created_at: 1785830100000, // epoch MILLISECONDS = Aug 2026
    entities_json: '',
    confidence: 0.8,
  },
]

const client = { stdbHost: '127.0.0.1', stdbPort: '3001', stdbDb: 'spacetime-memory-v2' }

describe('MemoryManager', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    ;(stdbQuery as ReturnType<typeof vi.fn>).mockImplementation((_c: any, table: string) => {
      if (table === 'workspace') return Promise.resolve(workspaces)
      if (table === 'memory') return Promise.resolve(memories)
      if (table === 'note') return Promise.resolve([])
      return Promise.resolve([])
    })
    ;(stdbSql as ReturnType<typeof vi.fn>).mockResolvedValue([])
  })

  it('renders memory timestamps as real dates (ms, not seconds → 2026, not 1970)', async () => {
    render(<MemoryManager {...client} />)

    // wait for workspaces to load, then pick one
    await waitFor(() => {
      expect(screen.getByRole('combobox')).toBeTruthy()
    })
    const sel = screen.getByRole('combobox')
    fireEvent.change(sel, { target: { value: 'ws-1' } })

    // memory content appears with the formatted date
    await waitFor(() => {
      expect(screen.getByText(/Calvin: thanks!/)).toBeTruthy()
    })
    const dateText = screen.getByText(/2026/).textContent ?? ''
    expect(dateText).toContain('2026')
    expect(dateText).not.toContain('1970')
    // sanity: exact known render for 1785830100000 ms
    expect(dateText).toMatch(/Aug 4, 2026/)
  })
})