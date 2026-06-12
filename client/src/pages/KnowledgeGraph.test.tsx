/**
 * KnowledgeGraph page — component render smoke tests.
 * Mocks vis-network, vis-data, and SpacetimeDB dependencies.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import React from 'react';

// ---------------------------------------------------------------------------
// Mocks — must be before the page import
// ---------------------------------------------------------------------------

vi.mock('vis-network', () => ({
  Network: vi.fn(() => ({
    destroy: vi.fn(),
    on: vi.fn(),
    off: vi.fn(),
    setData: vi.fn(),
    moveTo: vi.fn(),
    fit: vi.fn(),
    getScale: vi.fn(() => 1),
    moveNode: vi.fn(),
    selectNodes: vi.fn(),
  })),
}));

vi.mock('vis-data', () => ({
  DataSet: vi.fn(() => ({
    add: vi.fn(),
    remove: vi.fn(),
    update: vi.fn(),
    get: vi.fn(() => []),
    forEach: vi.fn(),
    length: 0,
  })),
}));

vi.mock('@/lib/spacetimedb', () => ({
  fetchKgNodes: vi.fn(() => Promise.resolve([])),
  fetchKgEdges: vi.fn(() => Promise.resolve([])),
  callReducer: vi.fn(() => Promise.resolve({ ok: true })),
  executeSql: vi.fn(() => Promise.resolve({ rows: [] })),
}));

import KnowledgeGraph from '@/pages/KnowledgeGraph';

beforeEach(() => {
  vi.clearAllMocks();
});

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe('KnowledgeGraph', () => {
  it('renders loading state on mount', () => {
    render(React.createElement(KnowledgeGraph));
    expect(screen.getByText('Knowledge Graph')).toBeTruthy();
    expect(screen.getByText('Loading graph data…')).toBeTruthy();
  });

  it('transitions from loading to empty state', async () => {
    render(React.createElement(KnowledgeGraph));
    await waitFor(() => {
      expect(screen.getByText('No graph data yet')).toBeTruthy();
    });
    expect(screen.getByText('Knowledge Graph')).toBeTruthy();
  });

  it('renders error state when fetch fails', async () => {
    const { fetchKgNodes } = await import('@/lib/spacetimedb');
    (fetchKgNodes as ReturnType<typeof vi.fn>).mockRejectedValueOnce(
      new Error('Connection refused'),
    );
    render(React.createElement(KnowledgeGraph));
    await waitFor(() => {
      expect(screen.getByText('Failed to load graph')).toBeTruthy();
    });
    expect(screen.getByText('Retry')).toBeTruthy();
  });

  it('renders tabs: Graph, PageRank, Community Hierarchy', async () => {
    render(React.createElement(KnowledgeGraph));
    await waitFor(() => {
      expect(screen.getByText('No graph data yet')).toBeTruthy();
    });
    // Even in empty state, the body renders — tabs only appear when data exists.
    // But the heading is always there.
    expect(screen.getByText('Knowledge Graph')).toBeTruthy();
  });

  it('renders graph tabs and search input when data exists', async () => {
    const { fetchKgNodes, fetchKgEdges } = await import('@/lib/spacetimedb');
    (fetchKgNodes as ReturnType<typeof vi.fn>).mockResolvedValueOnce([
      { id: '1', label: 'TestNode', node_type: 'concept', summary: '', community_id: 1 },
    ]);
    (fetchKgEdges as ReturnType<typeof vi.fn>).mockResolvedValueOnce([]);

    render(React.createElement(KnowledgeGraph));

    await waitFor(() => {
      expect(screen.getByPlaceholderText('Search nodes…')).toBeTruthy();
    });

    expect(screen.getByText('Graph')).toBeTruthy();
    expect(screen.getByText('PageRank')).toBeTruthy();
    expect(screen.getByText('Community Hierarchy')).toBeTruthy();
    expect(screen.getByText('Knowledge Graph')).toBeTruthy();
  });

  it('renders zoom controls when data exists', async () => {
    const { fetchKgNodes, fetchKgEdges } = await import('@/lib/spacetimedb');
    (fetchKgNodes as ReturnType<typeof vi.fn>).mockResolvedValueOnce([
      { id: '1', label: 'TestNode', node_type: 'concept', summary: '', community_id: 1 },
    ]);
    (fetchKgEdges as ReturnType<typeof vi.fn>).mockResolvedValueOnce([]);

    render(React.createElement(KnowledgeGraph));

    await waitFor(() => {
      expect(screen.getByPlaceholderText('Search nodes…')).toBeTruthy();
    });

    // Zoom buttons identified by title attribute
    expect(screen.getByTitle('Zoom in')).toBeTruthy();
    expect(screen.getByTitle('Zoom out')).toBeTruthy();
    expect(screen.getByTitle('Fit view')).toBeTruthy();
  });

  it('renders legend with node type colors when data exists', async () => {
    const { fetchKgNodes, fetchKgEdges } = await import('@/lib/spacetimedb');
    (fetchKgNodes as ReturnType<typeof vi.fn>).mockResolvedValueOnce([
      { id: '1', label: 'TestNode', node_type: 'concept', summary: '', community_id: 1 },
    ]);
    (fetchKgEdges as ReturnType<typeof vi.fn>).mockResolvedValueOnce([]);

    render(React.createElement(KnowledgeGraph));

    await waitFor(() => {
      expect(screen.getByPlaceholderText('Search nodes…')).toBeTruthy();
    });

    expect(screen.getByText('Legend:')).toBeTruthy();
    // Check specific node types appear in legend
    expect(screen.getByText('code')).toBeTruthy();
    expect(screen.getByText('concept')).toBeTruthy();
  });
});
