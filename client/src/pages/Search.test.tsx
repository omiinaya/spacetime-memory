/**
 * VeracityBadge — component unit tests.
 */
import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import React from 'react';

import { VeracityBadge, VERACITY_TIERS } from '@/components/VeracityBadge';

describe('VeracityBadge', () => {
  it('renders nothing when tier is undefined', () => {
    const { container } = render(React.createElement(VeracityBadge, { tier: undefined }));
    expect(container.firstChild).toBeNull();
  });

  it('renders nothing when tier is null', () => {
    const { container } = render(React.createElement(VeracityBadge, { tier: null }));
    expect(container.firstChild).toBeNull();
  });

  it('renders nothing when tier is empty string', () => {
    const { container } = render(React.createElement(VeracityBadge, { tier: '' }));
    expect(container.firstChild).toBeNull();
  });

  it('renders CERTAIN badge with correct text', () => {
    render(React.createElement(VeracityBadge, { tier: 'CERTAIN' }));
    expect(screen.getByText('Certain')).toBeTruthy();
    const badge = screen.getByTestId('veracity-badge');
    expect(badge.className).toContain('emerald');
  });

  it('renders HIGH badge with correct text', () => {
    render(React.createElement(VeracityBadge, { tier: 'HIGH' }));
    expect(screen.getByText('High')).toBeTruthy();
    const badge = screen.getByTestId('veracity-badge');
    expect(badge.className).toContain('blue');
  });

  it('renders MEDIUM badge with correct text', () => {
    render(React.createElement(VeracityBadge, { tier: 'MEDIUM' }));
    expect(screen.getByText('Medium')).toBeTruthy();
    const badge = screen.getByTestId('veracity-badge');
    expect(badge.className).toContain('yellow');
  });

  it('renders LOW badge with correct text', () => {
    render(React.createElement(VeracityBadge, { tier: 'LOW' }));
    expect(screen.getByText('Low')).toBeTruthy();
    const badge = screen.getByTestId('veracity-badge');
    expect(badge.className).toContain('orange');
  });

  it('renders SPECULATIVE badge with correct text', () => {
    render(React.createElement(VeracityBadge, { tier: 'SPECULATIVE' }));
    expect(screen.getByText('Speculative')).toBeTruthy();
    const badge = screen.getByTestId('veracity-badge');
    expect(badge.className).toContain('gray');
  });

  it('renders unknown tier with fallback styling', () => {
    render(React.createElement(VeracityBadge, { tier: 'UNKNOWN' }));
    expect(screen.getByText('UNKNOWN')).toBeTruthy();
    const badge = screen.getByTestId('veracity-badge');
    expect(badge.className).toContain('gray');
  });

  it('exports all 5 veracity tier labels', () => {
    expect(VERACITY_TIERS).toEqual(['CERTAIN', 'HIGH', 'MEDIUM', 'LOW', 'SPECULATIVE']);
  });
});

describe('Search page — veracity enrichment', () => {
  it('all tier labels are recognized by VeracityBadge', () => {
    for (const tier of VERACITY_TIERS) {
      const { unmount } = render(React.createElement(VeracityBadge, { tier }));
      expect(screen.getByTestId('veracity-badge')).toBeTruthy();
      unmount();
    }
  });
});
