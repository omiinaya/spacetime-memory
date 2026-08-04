import { describe, it, expect, vi } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import ProxyMetricsDashboard from './ProxyMetricsDashboard'

vi.mock('./lib/stdb', () => ({
  stdbSql: vi.fn(),
  sortDesc: (rows: any[], field: string) =>
    rows.slice().sort((a, b) => String(b[field] ?? '').localeCompare(String(a[field] ?? ''))),
}))

import { stdbSql } from './lib/stdb'

const rows = [
  {
    id: 's1',
    created_at: 1785830100000, // epoch MILLISECONDS → Aug 2026
    requests_total: 1000,
    tokens_total: 500000,
    errors_total: 3,
    duration_sum_micros: 50000,
    duration_count: 10,
    per_model_json: '{}',
    latency_percentiles_json: '{}',
    raw_metrics_text: '',
  },
]

describe('ProxyMetricsDashboard timestamp formatting', () => {
  it('renders created_at as a real date (ms, not seconds → 2026, not 1970)', async () => {
    ;(stdbSql as ReturnType<typeof vi.fn>).mockResolvedValue(rows)
    render(<ProxyMetricsDashboard />)
    await waitFor(() => {
      expect(screen.getByText(/2026/)).toBeTruthy()
    })
    const cell = screen.getByText(/2026/)
    expect(cell.textContent).toContain('2026')
    expect(cell.textContent).not.toContain('1970')
    // known ms value renders as Aug 2026 (toLocaleString → 8/4/2026)
    expect(cell.textContent).toMatch(/8\/4\/2026/)
  })
})