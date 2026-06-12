/**
 * Smoke tests — verify key pages render without crashing.
 * Mocks SpacetimeDB dependencies so no live connection is needed.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen } from '@testing-library/react';
import React from 'react';

// ---------------------------------------------------------------------------
// Mocks — must be before any imports that transitively pull in mocked modules
// ---------------------------------------------------------------------------

// Mock wouter (used by NotesList, Layout)
vi.mock('wouter', () => ({
  useLocation: () => ['/notes', vi.fn()],
  Link: ({ children, ...props }: any) => React.createElement('a', props, children),
  Route: ({ children }: any) => React.createElement('div', null, children),
  Switch: ({ children }: any) => React.createElement('div', null, children),
  useRoute: () => [false, {}],
}));

// Mock spacetimedb module
vi.mock('@/lib/spacetimedb', () => ({
  getConnection: vi.fn(() => ({
    db: new Map(),
    reducers: {},
  })),
  isReady: vi.fn(() => true),
  getError: vi.fn(() => null),
  onReady: vi.fn(),
  subscribe: vi.fn(),
  getDashboardStats: vi.fn(() => ({
    workspaceCount: 3,
    peerCount: 5,
    memoryCount: 1420,
    sessionCount: 28,
  })),
  getRecentActivity: vi.fn(() => []),
  callReducer: vi.fn(() => Promise.resolve({ ok: true })),
  executeSql: vi.fn(() => Promise.resolve({ rows: [] })),
  parseSqlResponse: vi.fn(() => []),
  formatMemoryTimestamp: vi.fn((ts: string | null) => ts || '—'),
  fetchKgNodes: vi.fn(() => Promise.resolve([])),
  fetchKgEdges: vi.fn(() => Promise.resolve([])),
}));

// Mock useReactiveDb
vi.mock('@/lib/useReactiveDb', () => ({
  useReactiveDb: vi.fn(() => ({
    ready: true,
    error: null,
    stats: { workspaceCount: 3, peerCount: 5, memoryCount: 1420, sessionCount: 28 },
    activity: [],
  })),
  useTable: vi.fn(() => ({
    data: [],
    loading: false,
    error: null,
  })),
  initReactiveDb: vi.fn(),
}));

// Mock vis-network + vis-data (used by KnowledgeGraph)
vi.mock('vis-network', () => ({
  Network: vi.fn(),
}));
vi.mock('vis-data', () => ({
  DataSet: vi.fn(() => []),
}));

// ---------------------------------------------------------------------------
// Pages
// ---------------------------------------------------------------------------
import Dashboard from '@/pages/Dashboard';
import Search from '@/pages/Search';
import MemoryBrowser from '@/pages/MemoryBrowser';
import NotesList from '@/pages/NotesList';

beforeEach(() => {
  vi.clearAllMocks();
});

// ---------------------------------------------------------------------------
// Dashboard
// ---------------------------------------------------------------------------
describe('Dashboard', () => {
  it('renders dashboard heading', () => {
    render(React.createElement(Dashboard));
    expect(screen.getByText('Dashboard')).toBeTruthy();
  });

  it('renders stat cards — Total Memories, Active Peers, Sessions, Workspaces', () => {
    render(React.createElement(Dashboard));
    expect(screen.getByText('Total Memories')).toBeTruthy();
    expect(screen.getByText('Active Peers')).toBeTruthy();
    expect(screen.getByText('Sessions Today')).toBeTruthy();
    expect(screen.getByText('Workspaces')).toBeTruthy();
  });
});

// ---------------------------------------------------------------------------
// Search
// ---------------------------------------------------------------------------
describe('Search', () => {
  it('renders search page heading', () => {
    render(React.createElement(Search));
    expect(screen.getByRole('heading', { name: 'Search' })).toBeTruthy();
  });

  it('renders the search input', () => {
    render(React.createElement(Search));
    const input = screen.getByPlaceholderText(/search/i);
    expect(input).toBeTruthy();
  });
});

// ---------------------------------------------------------------------------
// MemoryBrowser
// ---------------------------------------------------------------------------
describe('MemoryBrowser', () => {
  it('renders memory browser heading', () => {
    render(React.createElement(MemoryBrowser));
    expect(screen.getByText('Memory Browser')).toBeTruthy();
  });

  it('renders search input', () => {
    render(React.createElement(MemoryBrowser));
    const input = screen.getByPlaceholderText(/search|filter/i);
    expect(input).toBeTruthy();
  });
});

// ---------------------------------------------------------------------------
// NotesList
// ---------------------------------------------------------------------------
describe('NotesList', () => {
  it('renders notes heading', () => {
    render(React.createElement(NotesList));
    expect(screen.getByText('Notes')).toBeTruthy();
  });
});

// ---------------------------------------------------------------------------
// KnowledgeGraph — vis-network heavy, verify heading renders
// ---------------------------------------------------------------------------
import KnowledgeGraph from '@/pages/KnowledgeGraph';

describe('KnowledgeGraph', () => {
  it('renders knowledge graph heading', () => {
    render(React.createElement(KnowledgeGraph));
    expect(screen.getByRole('heading', { name: /knowledge graph/i })).toBeTruthy();
  });
});

// ---------------------------------------------------------------------------
// SmartQuery — complex page with tabs, verify renders
// ---------------------------------------------------------------------------
import SmartQuery from '@/pages/SmartQuery';

describe('SmartQuery', () => {
  it('renders smart query heading', () => {
    render(React.createElement(SmartQuery));
    expect(screen.getByRole('heading', { name: /smart query/i })).toBeTruthy();
  });
});

// ---------------------------------------------------------------------------
// Sessions — verify heading renders
// ---------------------------------------------------------------------------
import Sessions from '@/pages/Sessions';

describe('Sessions', () => {
  it('renders sessions heading', () => {
    render(React.createElement(Sessions));
    expect(screen.getByRole('heading', { name: /sessions/i })).toBeTruthy();
  });
});

// ---------------------------------------------------------------------------
// TrajectoryViz — complex page with vis-network, verify renders
// ---------------------------------------------------------------------------
import TrajectoryViz from '@/pages/TrajectoryViz';

describe('TrajectoryViz', () => {
  it('renders trajectory viz heading', () => {
    render(React.createElement(TrajectoryViz));
    expect(screen.getByRole('heading', { name: /trajectory/i })).toBeTruthy();
  });
});
