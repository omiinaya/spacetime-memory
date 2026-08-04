import { describe, it, expect, vi } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import KGExplorer from './KGExplorer'

// Mock stdbSql so the component doesn't need a live STDB.
vi.mock('./lib/stdb', () => ({
  stdbSql: vi.fn(),
}))

import { stdbSql } from './lib/stdb'

const sampleNodes = [
  { id: '1', label: 'GitHub', node_type: 'entity', summary: 'code host' },
  { id: '2', label: 'Models', node_type: 'concept', summary: 'ml models' },
  { id: '3', label: 'tensorflow', node_type: 'code', summary: 'framework' },
]

const client = { host: '127.0.0.1', port: '3001', db: 'spacetime-memory-v2', workspaceId: 'ws-1' }

describe('KGExplorer search', () => {
  it('filters nodes client-side, case-insensitively, when LIKE is unsupported by STDB', async () => {
    ;(stdbSql as ReturnType<typeof vi.fn>).mockResolvedValue(sampleNodes)
    render(<KGExplorer {...client} />)

    // type a search label with wrong case — should still match (GitHub)
    fireEvent.change(screen.getByPlaceholderText('Search nodes by label...'), {
      target: { value: 'github' },
    })
    fireEvent.click(screen.getByText('Search'))

    await waitFor(() => {
      expect(screen.getByText('GitHub')).toBeTruthy()
    })
    // non-matching should be absent
    expect(screen.queryByText('Models')).toBeNull()
    expect(screen.queryByText('tensorflow')).toBeNull()
  })

  it('shows all nodes when search is empty', async () => {
    ;(stdbSql as ReturnType<typeof vi.fn>).mockResolvedValue(sampleNodes)
    render(<KGExplorer {...client} />)
    fireEvent.click(screen.getByText('Search'))
    await waitFor(() => {
      expect(screen.getByText('GitHub')).toBeTruthy()
    })
    expect(screen.getByText('Models')).toBeTruthy()
    expect(screen.getByText('tensorflow')).toBeTruthy()
  })

  it('does not send LIKE in the SQL query (uses capped SELECT + client filter)', async () => {
    ;(stdbSql as ReturnType<typeof vi.fn>).mockResolvedValue(sampleNodes)
    render(<KGExplorer {...client} />)
    fireEvent.click(screen.getByText('Search'))
    await waitFor(() => {
      expect(stdbSql).toHaveBeenCalled()
    })
    // verify no LIKE clause was ever sent
    const sql = (stdbSql as ReturnType<typeof vi.fn>).mock.calls[0][1] as string
    expect(sql).not.toContain('LIKE')
    expect(sql).toContain('LIMIT 1000')
  })
})