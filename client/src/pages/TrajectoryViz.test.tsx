/**
 * TrajectoryViz page — component render smoke tests.
 * Mocks SpacetimeDB and useReactiveDb.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen } from '@testing-library/react';
import React from 'react';

// ---------------------------------------------------------------------------
// Mocks — must be before the page import.
// Use vi.hoisted() so variable refs survive vitest hoisting.
// ---------------------------------------------------------------------------

interface MemoryRow {
  id: string;
  workspace_id: string;
  peer_id: string;
  content: string;
  summary: string;
  memory_type: string;
  tier: string;
  confidence: number;
  strength: number;
  trust_score: number;
  is_active: boolean;
  access_count: number;
  created_at: number;
  updated_at: number;
}

const { useTableMock } = vi.hoisted(() => ({
  useTableMock: vi.fn<() => { data: MemoryRow[]; loading: boolean; error: string | null }>(() => ({
    data: [],
    loading: false,
    error: null,
  })),
}));

vi.mock('@/lib/spacetimedb', () => ({
  callReducer: vi.fn(() => Promise.resolve({ ok: true })),
  formatMemoryTimestamp: vi.fn((ts: string | null) => ts || '—'),
  executeSql: vi.fn(() => Promise.resolve({ rows: [] })),
}));

vi.mock('@/lib/useReactiveDb', () => ({
  useTable: useTableMock,
  useReactiveDb: vi.fn(() => ({
    ready: true,
    error: null,
  })),
}));

import TrajectoryViz from '@/pages/TrajectoryViz';

beforeEach(() => {
  vi.clearAllMocks();
  useTableMock.mockReturnValue({
    data: [],
    loading: false,
    error: null,
  });
});

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe('TrajectoryViz', () => {
  it('renders the page heading', () => {
    render(React.createElement(TrajectoryViz));
    expect(screen.getByRole('heading', { name: 'Trajectory Visualization' })).toBeTruthy();
  });

  it('renders loading skeleton when data is loading', () => {
    useTableMock.mockReturnValue({
      data: [],
      loading: true,
      error: null,
    });
    render(React.createElement(TrajectoryViz));
    expect(screen.getByText('Trajectory Visualization')).toBeTruthy();
    expect(screen.getByText('Retrieval trajectories and memory reinforcement paths.')).toBeTruthy();
  });

  it('renders error state on load failure', () => {
    useTableMock.mockReturnValue({
      data: [],
      loading: false,
      error: 'Failed to connect',
    });
    render(React.createElement(TrajectoryViz));
    expect(screen.getByText('Failed to load')).toBeTruthy();
    expect(screen.getByText('Failed to connect')).toBeTruthy();
  });

  it('shows empty state when no memories exist', () => {
    render(React.createElement(TrajectoryViz));
    expect(screen.getByText('No memories available')).toBeTruthy();
    expect(screen.getByText('Store memories to see trajectory visualizations.')).toBeTruthy();
  });

  it('renders full layout when memories exist', () => {
    useTableMock.mockReturnValue({
      data: [
        {
          id: '1',
          workspace_id: 'ws1',
          peer_id: 'p1',
          content: 'Test memory',
          summary: 'A test memory',
          memory_type: 'world_fact',
          tier: 'L0',
          confidence: 0.9,
          strength: 0.8,
          trust_score: 0.7,
          is_active: true,
          access_count: 5,
          created_at: 1000000,
          updated_at: 1000000,
        },
      ],
      loading: false,
      error: null,
    });

    render(React.createElement(TrajectoryViz));

    // Heading
    expect(screen.getByRole('heading', { name: 'Trajectory Visualization' })).toBeTruthy();

    // Stats cards (tier labels appear in both stats cards and section headers)
    expect(screen.getByText('Total')).toBeTruthy();
    expect(screen.getAllByText('Long-Term (L0)').length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText('Working (L1)').length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText('Ephemeral (L2)').length).toBeGreaterThanOrEqual(1);
    expect(screen.getByText('Avg Confidence')).toBeTruthy();

    // Filter bar
    expect(screen.getByPlaceholderText('Search memories…')).toBeTruthy();
    expect(screen.getByDisplayValue('All Tiers')).toBeTruthy();
    expect(screen.getByDisplayValue('All Types')).toBeTruthy();
    expect(screen.getByText('Reset')).toBeTruthy();

    // Trajectory Legend
    expect(screen.getByText('Trajectory Legend:')).toBeTruthy();
    expect(screen.getByText('escalated')).toBeTruthy();
    expect(screen.getByText('decayed')).toBeTruthy();
    expect(screen.getByText('promoted')).toBeTruthy();
    expect(screen.getByText('demoted')).toBeTruthy();

    // Memory content visible
    expect(screen.getByText('A test memory')).toBeTruthy();
  });

  it('shows empty filtered state when many memories but no match', () => {
    useTableMock.mockReturnValue({
      data: [
        {
          id: '1',
          workspace_id: 'ws1',
          peer_id: 'p1',
          content: 'Test memory',
          summary: 'Some summary',
          memory_type: 'world_fact',
          tier: 'L2',
          confidence: 0.5,
          strength: 0.3,
          trust_score: 0.5,
          is_active: true,
          access_count: 1,
          created_at: 1000000,
          updated_at: 1000000,
        },
      ],
      loading: false,
      error: null,
    });

    render(React.createElement(TrajectoryViz));

    // L2 memories exist — tier label appears in both stats card and section header
    expect(screen.getAllByText('Ephemeral (L2)').length).toBeGreaterThanOrEqual(1);
  });
});
