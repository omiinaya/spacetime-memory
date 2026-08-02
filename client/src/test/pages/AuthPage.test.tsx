/**
 * AuthPage — smoke test with mocked auth context.
 */
import { describe, it, expect, vi } from 'vitest';
import { act, render } from '@testing-library/react';
import React from 'react';

vi.mock('wouter', () => ({
  useLocation: () => ['/auth', vi.fn()],
  Link: ({ children, ...props }: any) => React.createElement('a', props, children),
  Route: ({ children }: any) => React.createElement('div', null, children),
  Switch: ({ children }: any) => React.createElement('div', null, children),
  useRoute: () => [false, {}],
}));

vi.mock('@/lib/spacetimedb', () => ({
  getConnection: vi.fn(() => ({ db: new Map(), reducers: {} })),
  isReady: vi.fn(() => true),
  getError: vi.fn(() => null),
  onReady: vi.fn(),
  subscribe: vi.fn(),
  callReducer: vi.fn(() => Promise.resolve({ ok: true })),
  executeSql: vi.fn(() => Promise.resolve({ rows: [] })),
  parseSqlResponse: vi.fn(() => []),
  formatMemoryTimestamp: vi.fn((ts: string | null) => ts || '—'),
  fetchKgNodes: vi.fn(() => Promise.resolve([])),
  fetchKgEdges: vi.fn(() => Promise.resolve([])),
}));

vi.mock('@/lib/useReactiveDb', () => ({
  useReactiveDb: vi.fn(() => ({
    ready: true, error: null,
    stats: { workspaceCount: 3, peerCount: 5, memoryCount: 1420, sessionCount: 28 },
    activity: [],
  })),
  useTable: vi.fn(() => ({ data: [], loading: false, error: null })),
  initReactiveDb: vi.fn(),
}));

const mockRegister = vi.fn(() => Promise.resolve());
const mockLogin = vi.fn(() => Promise.resolve());
const mockLogout = vi.fn(() => Promise.resolve());

vi.mock('@/lib/auth', () => ({
  useAuth: () => ({
    status: { type: 'authenticated' as const, account: { id: '1', username: 'test', display_name: 'Test User', role: 'admin', is_active: true } },
    register: mockRegister,
    login: mockLogin,
    logout: mockLogout,
  }),
}));

import AuthPage from '@/pages/AuthPage';

describe('AuthPage', () => {
  it('renders without crashing', async () => {
    const { container } = render(React.createElement(AuthPage));
    expect(container).toBeTruthy();
    await act(async () => {});
  });
});
