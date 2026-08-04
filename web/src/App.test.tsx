import { describe, it, expect } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import App from './App'

describe('App navigation', () => {
  it('renders all six tabs', () => {
    render(<App />)
    expect(screen.getByText('Proxy Metrics')).toBeTruthy()
    expect(screen.getByText('Embedder Metrics')).toBeTruthy()
    expect(screen.getByText('Memory Manager')).toBeTruthy()
    expect(screen.getByText('🕸 Knowledge Graph')).toBeTruthy()
    expect(screen.getByText('🏆 Benchmarks')).toBeTruthy()
    expect(screen.getByText('Connection Wizard')).toBeTruthy()
  })

  it('shows the Knowledge Graph view with workspace input when the KG tab is clicked', () => {
    render(<App />)
    fireEvent.click(screen.getByText('🕸 Knowledge Graph'))
    expect(screen.getByText('Knowledge Graph')).toBeTruthy()
    // workspace selector present
    expect(screen.getByPlaceholderText('Workspace ID')).toBeTruthy()
    // KGExplorer mounts (its Search control renders)
    expect(screen.getByPlaceholderText('Search nodes by label...')).toBeTruthy()
    expect(screen.getByText('Search')).toBeTruthy()
  })

  it('switches back to the default Proxy Metrics view', () => {
    render(<App />)
    fireEvent.click(screen.getByText('🕸 Knowledge Graph'))
    fireEvent.click(screen.getByText('Proxy Metrics'))
    expect(screen.getByText('Proxy Metrics')).toBeTruthy()
  })
})
