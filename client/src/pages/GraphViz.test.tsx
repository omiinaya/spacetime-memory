/**
 * GraphViz page — component render smoke tests.
 * Mocks d3-force, d3-drag, d3-zoom, d3-selection, wouter, and SpacetimeDB.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { act, render, screen, waitFor } from '@testing-library/react';
import React from 'react';

// ---------------------------------------------------------------------------
// Mocks — must be before the page import.
// Use vi.hoisted() so variable refs survive hoisting.
// ---------------------------------------------------------------------------

const { d3SelectMock } = vi.hoisted(() => {
  const chained = () => chained;
  chained.selectAll = vi.fn(() => chained);
  chained.select = vi.fn(() => chained);
  chained.data = vi.fn(() => chained);
  chained.join = vi.fn(() => chained);
  chained.enter = vi.fn(() => chained);
  chained.append = vi.fn(() => chained);
  chained.attr = vi.fn(() => chained);
  chained.style = vi.fn(() => chained);
  chained.text = vi.fn(() => chained);
  chained.on = vi.fn(() => chained);
  chained.call = vi.fn(() => chained);
  chained.node = vi.fn(() => ({ getBoundingClientRect: () => ({ width: 800, height: 600 }) }));
  chained.remove = vi.fn();
  chained.filter = vi.fn(() => chained);
  chained.raise = vi.fn();
  chained.lower = vi.fn();
  chained.merge = vi.fn(() => chained);
  chained.transition = vi.fn(() => chained);
  chained.duration = vi.fn(() => chained);
  return { d3SelectMock: vi.fn(() => chained) };
});

vi.mock('d3-selection', () => ({
  select: d3SelectMock,
  selectAll: d3SelectMock,
}));

vi.mock('d3-force', () => ({
  forceSimulation: vi.fn(() => ({
    nodes: vi.fn().mockReturnThis(),
    force: vi.fn().mockReturnThis(),
    on: vi.fn().mockReturnThis(),
    stop: vi.fn(),
    tick: vi.fn(),
    alpha: vi.fn(),
    alphaTarget: vi.fn(),
    restart: vi.fn(),
  })),
  forceLink: vi.fn(() => ({ id: vi.fn().mockReturnThis(), distance: vi.fn().mockReturnThis(), strength: vi.fn().mockReturnThis(), links: vi.fn().mockReturnThis() })),
  forceManyBody: vi.fn(() => ({ strength: vi.fn().mockReturnThis(), distanceMin: vi.fn().mockReturnThis(), distanceMax: vi.fn().mockReturnThis(), theta: vi.fn().mockReturnThis() })),
  forceCenter: vi.fn(() => ({ x: vi.fn().mockReturnThis(), y: vi.fn().mockReturnThis(), strength: vi.fn().mockReturnThis() })),
  forceCollide: vi.fn(() => ({ radius: vi.fn().mockReturnThis(), strength: vi.fn().mockReturnThis(), iterations: vi.fn().mockReturnThis() })),
}));

vi.mock('d3-drag', () => ({
  drag: vi.fn(() => ({
    on: vi.fn().mockReturnThis(),
    filter: vi.fn().mockReturnThis(),
    subject: vi.fn().mockReturnThis(),
    container: vi.fn().mockReturnThis(),
  })),
}));

vi.mock('d3-zoom', () => ({
  zoom: vi.fn(() => ({
    scaleExtent: vi.fn().mockReturnThis(),
    on: vi.fn().mockReturnThis(),
    filter: vi.fn().mockReturnThis(),
    translateExtent: vi.fn().mockReturnThis(),
  })),
  zoomIdentity: { k: 1, x: 0, y: 0 },
}));

vi.mock('d3-shape', () => ({
  line: vi.fn(() => vi.fn(() => '')),
  curveCatmullRom: {},
}));

vi.mock('d3-scale', () => {
  const fn: any = vi.fn((v: number) => v);
  fn.domain = vi.fn().mockReturnThis();
  fn.range = vi.fn().mockReturnThis();
  return { scaleLinear: vi.fn(() => fn) };
});

vi.mock('wouter', () => ({
  useLocation: () => ['/graphviz', vi.fn()],
  Link: ({ children, ...props }: any) => React.createElement('a', props, children),
  Route: ({ children }: any) => React.createElement('div', null, children),
  useRoute: () => [false, {}],
}));

vi.mock('@/lib/spacetimedb', () => ({
  fetchKgNodes: vi.fn(() => Promise.resolve([])),
  fetchKgEdges: vi.fn(() => Promise.resolve([])),
}));

import GraphViz from '@/pages/GraphViz';

beforeEach(() => {
  vi.clearAllMocks();
});

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe('GraphViz', () => {
  it('renders loading state on mount', async () => {
    render(React.createElement(GraphViz));
    expect(screen.getByText('Graph Visualization')).toBeTruthy();
    expect(screen.getByText('Building graph layout…')).toBeTruthy();
    await act(async () => {});
  });

  it('transitions from loading to empty state', async () => {
    render(React.createElement(GraphViz));
    await waitFor(() => {
      expect(screen.getByText('No graph data yet')).toBeTruthy();
    });
    expect(screen.getByText('Graph Visualization')).toBeTruthy();
  });

  it('renders error state when fetch fails', async () => {
    const { fetchKgNodes } = await import('@/lib/spacetimedb');
    (fetchKgNodes as ReturnType<typeof vi.fn>).mockRejectedValueOnce(
      new Error('Network error'),
    );
    render(React.createElement(GraphViz));
    await waitFor(() => {
      expect(screen.getByText('Failed to load graph')).toBeTruthy();
    });
    expect(screen.getByText('Retry')).toBeTruthy();
  });

  it('renders stats bar and controls when data exists', async () => {
    const { fetchKgNodes, fetchKgEdges } = await import('@/lib/spacetimedb');
    (fetchKgNodes as ReturnType<typeof vi.fn>).mockResolvedValueOnce([
      { id: '1', label: 'Alpha', node_type: 'concept', summary: '', community_id: 1, strength: 1 },
      { id: '2', label: 'Beta', node_type: 'code', summary: '', community_id: 2, strength: 1 },
    ]);
    (fetchKgEdges as ReturnType<typeof vi.fn>).mockResolvedValueOnce([
      { id: 'e1', source_node_id: '1', target_node_id: '2', relation: 'depends_on', weight: 1, confidence: 'EXTRACTED' },
    ]);

    render(React.createElement(GraphViz));

    await waitFor(() => {
      expect(screen.getByPlaceholderText('Search nodes…')).toBeTruthy();
    });

    expect(screen.getByText('nodes')).toBeTruthy();
    expect(screen.getByText('edges')).toBeTruthy();
    expect(screen.getByText('communities')).toBeTruthy();
    expect(screen.getByPlaceholderText('Search nodes…')).toBeTruthy();
  });

  it('renders zoom controls', async () => {
    const { fetchKgNodes, fetchKgEdges } = await import('@/lib/spacetimedb');
    (fetchKgNodes as ReturnType<typeof vi.fn>).mockResolvedValueOnce([
      { id: '1', label: 'Node', node_type: 'concept', summary: '', community_id: 1, strength: 1 },
    ]);
    (fetchKgEdges as ReturnType<typeof vi.fn>).mockResolvedValueOnce([]);

    render(React.createElement(GraphViz));
    await waitFor(() => {
      expect(screen.getByPlaceholderText('Search nodes…')).toBeTruthy();
    });

    expect(screen.getByTitle('Zoom in')).toBeTruthy();
    expect(screen.getByTitle('Zoom out')).toBeTruthy();
    expect(screen.getByTitle('Reset zoom')).toBeTruthy();
  });

  it('renders view controls: labels, physics, color mode', async () => {
    const { fetchKgNodes, fetchKgEdges } = await import('@/lib/spacetimedb');
    (fetchKgNodes as ReturnType<typeof vi.fn>).mockResolvedValueOnce([
      { id: '1', label: 'Node', node_type: 'concept', summary: '', community_id: 1, strength: 1 },
    ]);
    (fetchKgEdges as ReturnType<typeof vi.fn>).mockResolvedValueOnce([]);

    render(React.createElement(GraphViz));
    await waitFor(() => {
      expect(screen.getByPlaceholderText('Search nodes…')).toBeTruthy();
    });

    expect(screen.getByText(/Labels/)).toBeTruthy();
    expect(screen.getByText(/Physics/)).toBeTruthy();
    expect(screen.getByText(/Color by/)).toBeTruthy();
  });

  it('renders type filter checkboxes', async () => {
    const { fetchKgNodes, fetchKgEdges } = await import('@/lib/spacetimedb');
    (fetchKgNodes as ReturnType<typeof vi.fn>).mockResolvedValueOnce([
      { id: '1', label: 'Node', node_type: 'concept', summary: '', community_id: 1, strength: 1 },
    ]);
    (fetchKgEdges as ReturnType<typeof vi.fn>).mockResolvedValueOnce([]);

    render(React.createElement(GraphViz));
    await waitFor(() => {
      expect(screen.getByPlaceholderText('Search nodes…')).toBeTruthy();
    });

    expect(screen.getByText('Filter by type')).toBeTruthy();
    expect(screen.getByText('concept')).toBeTruthy();
    expect(screen.getByText('code')).toBeTruthy();
    expect(screen.getByText('entity')).toBeTruthy();
    expect(screen.getByText('document')).toBeTruthy();
    expect(screen.getByText('topic')).toBeTruthy();
  });
});
