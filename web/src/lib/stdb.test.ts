import { describe, it, expect, vi, beforeEach } from 'vitest'
import { parseSqlResponse, sortDesc, stdbSql, stdbQuery } from './stdb'

describe('parseSqlResponse', () => {
  it('parses STDB positional-array responses into row dicts', () => {
    const raw = JSON.stringify([
      {
        schema: { elements: [{ name: { some: 'id' } }, { name: { some: 'content' } }] },
        rows: [
          ['abc-123', 'Hello world'],
          ['def-456', 'Second row'],
        ],
      },
    ])
    const rows = parseSqlResponse(raw)
    expect(rows).toEqual([
      { id: 'abc-123', content: 'Hello world' },
      { id: 'def-456', content: 'Second row' },
    ])
  })

  it('handles multiple tables in one response', () => {
    const raw = JSON.stringify([
      { schema: { elements: [{ name: { some: 'a' } }] }, rows: [[1]] },
      { schema: { elements: [{ name: { some: 'b' } }] }, rows: [[2], [3]] },
    ])
    expect(parseSqlResponse(raw)).toEqual([{ a: 1 }, { b: 2 }, { b: 3 }])
  })

  it('returns empty for empty input', () => {
    expect(parseSqlResponse('')).toEqual([])
    expect(parseSqlResponse('  ')).toEqual([])
    expect(parseSqlResponse('not json')).toEqual([])
  })

  it('handles missing/unnamed columns defensively', () => {
    const raw = JSON.stringify([{ schema: { elements: [{ name: null }] }, rows: [['x']] }])
    expect(parseSqlResponse(raw)).toEqual([{ '?col?': 'x' }])
  })
})

describe('sortDesc', () => {
  it('sorts by created_at descending', () => {
    const rows = [
      { id: 'a', created_at: '2026-01-01' },
      { id: 'b', created_at: '2026-03-01' },
      { id: 'c', created_at: '2026-02-01' },
    ]
    expect(sortDesc(rows, 'created_at').map(r => r.id)).toEqual(['b', 'c', 'a'])
  })

  it('does not mutate the input array', () => {
    const rows = [{ id: 'a', created_at: 1 }, { id: 'b', created_at: 2 }]
    const copy = rows.slice()
    sortDesc(rows, 'created_at')
    expect(rows).toEqual(copy)
  })

  it('handles missing field values', () => {
    const rows = [{ id: 'a' }, { id: 'b', created_at: 10 }]
    expect(sortDesc(rows, 'created_at')).toHaveLength(2)
  })
})

describe('stdbSql', () => {
  beforeEach(() => vi.restoreAllMocks())

  it('sends raw SQL text (not JSON) and parses the positional response', async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      text: async () => JSON.stringify([
        { schema: { elements: [{ name: { some: 'id' } }] }, rows: [['r1']] },
      ]),
    })
    vi.stubGlobal('fetch', fetchMock)

    const rows = await stdbSql({ host: 'h', port: '5190', database: 'db' }, 'SELECT * FROM memory LIMIT 1')
    expect(rows).toEqual([{ id: 'r1' }])

    const [url, opts] = fetchMock.mock.calls[0]
    expect(url).toBe('http://h:5190/v1/database/db/sql')
    expect(opts.body).toBe('SELECT * FROM memory LIMIT 1') // raw text, not JSON.stringify
    expect(opts.headers['Content-Type']).toBe('text/plain')
  })

  it('throws a descriptive error on non-ok response', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
      ok: false,
      status: 400,
      text: async () => 'sql parser error',
    }))
    await expect(stdbSql({ host: 'h', port: '5190', database: 'db' }, 'BAD SQL'))
      .rejects.toThrow('STDB error: 400')
  })
})

describe('stdbQuery', () => {
  beforeEach(() => vi.restoreAllMocks())

  it('posts reducer-query JSON and returns rows', async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => [{ id: 'ws-1', name: 'Test WS' }],
    })
    vi.stubGlobal('fetch', fetchMock)

    const rows = await stdbQuery(
      { host: 'h', port: '5190', database: 'db' },
      'workspace',
      '',
      {},
      ['id', 'name'],
    )
    expect(rows).toEqual([{ id: 'ws-1', name: 'Test WS' }])

    const [url, opts] = fetchMock.mock.calls[0]
    expect(url).toBe('http://h:5190/v1/database/db/query')
    const body = JSON.parse(opts.body)
    expect(body).toEqual({ table: 'workspace', workspace_id: '', filter: {}, columns: ['id', 'name'] })
  })

  it('throws a descriptive error on non-ok response', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
      ok: false,
      status: 500,
      text: async () => 'boom',
    }))
    await expect(stdbQuery({ host: 'h', port: '5190', database: 'db' }, 'note'))
      .rejects.toThrow('STDB query error: 500')
  })
})
