import { useState, useMemo, useRef, useCallback, useEffect } from 'react';
import { useLocation, Link } from 'wouter';
import {
  Share2, Loader2, FileText, Search,
  X, ExternalLink, CornerDownRight,
  ArrowLeft, ZoomIn, MessageSquare, Filter,
} from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Badge } from '@/components/ui/badge';
import { useTable } from '@/lib/useReactiveDb';
import { MarkdownRenderer } from '@/components/MarkdownRenderer';
import { cn } from '@/lib/utils';

// ── Types matching actual DB tables ──

interface NoteRow {
  id: string;
  title: string;
  content: string;
  note_date?: string;
  backlink_count?: number;
  block_ref_count?: number;
  updated_at: number;
  is_active?: boolean;
}

interface NoteBlockRow {
  id: string;
  note_id: string;
  block_type: string;
  content: string;
  source?: string;
  block_order?: number;
  heading_level?: number;
  task_state?: string;
  properties_json?: string;
  is_active?: boolean;
  created_at: number;
}

interface BlockReferenceRow {
  id: string;
  source_note_id?: string;
  source_block_id: string;
  target_block_id: string;
  target_note_id?: string;
  ref_type: string;
  context?: string;
  created_at: number;
}

// ── Constants ──

const BLOCK_TYPE_COLORS: Record<string, string> = {
  heading: 'bg-blue-500/15 text-blue-400 border-blue-500/30',
  list: 'bg-green-500/15 text-green-400 border-green-500/30',
  todo: 'bg-amber-500/15 text-amber-400 border-amber-500/30',
  quote: 'bg-purple-500/15 text-purple-400 border-purple-500/30',
  code: 'bg-red-500/15 text-red-400 border-red-500/30',
};

const BLOCK_TYPE_BORDER: Record<string, string> = {
  heading: 'border-l-blue-500',
  list: 'border-l-green-500',
  todo: 'border-l-amber-500',
  quote: 'border-l-purple-500',
  code: 'border-l-red-500',
};

const NODE_W = 220;
const NODE_H = 96;
const RADIAL_SPACING = 280;

function truncate(text: string, maxLen: number): string {
  if (!text) return '(empty)';
  return text.length > maxLen ? text.slice(0, maxLen) + '…' : text;
}

function shortId(blockId: string): string {
  return blockId.split(':').pop() || blockId;
}

// ── Layout: radial approximation from most-connected nodes ──

interface LayoutNode {
  blockId: string;
  x: number;
  y: number;
}

function computeLayout(
  allBlockIds: Set<string>,
  connections: Map<string, Set<string>>,
): Map<string, LayoutNode> {
  const layout = new Map<string, LayoutNode>();
  const placed = new Set<string>();

  // Nodes sorted by connection count (most connected first)
  const sorted = [...allBlockIds]
    .map(id => ({ id, degree: (connections.get(id)?.size ?? 0) }))
    .sort((a, b) => b.degree - a.degree);

  const cols = Math.max(1, Math.ceil(Math.sqrt(sorted.length)));
  const spacing = RADIAL_SPACING;
  const startX = 60;
  const startY = 40;

  for (let i = 0; i < sorted.length; i++) {
    const { id } = sorted[i];
    if (placed.has(id)) continue;

    // Place this hub near center-ish
    const col = i % cols;
    const row = Math.floor(i / cols);
    const hx = startX + col * spacing * 0.9;
    const hy = startY + row * spacing * 0.9;

    layout.set(id, { blockId: id, x: hx, y: hy });
    placed.add(id);

    // Place its unplaced neighbors around it
    const neighbors = connections.get(id);
    if (neighbors) {
      const unplaced = [...neighbors].filter(n => !placed.has(n));
      unplaced.forEach((nid, j) => {
        const angle = (j / Math.max(1, unplaced.length)) * Math.PI * 2 - Math.PI / 2;
        const dist = spacing * 0.85;
        layout.set(nid, {
          blockId: nid,
          x: hx + Math.cos(angle) * dist,
          y: hy + Math.sin(angle) * dist,
        });
        placed.add(nid);
      });
    }
  }

  // Ensure no overlaps — lightly spread out
  const entries = [...layout.entries()];
  for (let iter = 0; iter < 5; iter++) {
    for (const [idA, nodeA] of entries) {
      for (const [idB, nodeB] of entries) {
        if (idA >= idB) continue;
        const dx = nodeB.x - nodeA.x;
        const dy = nodeB.y - nodeA.y;
        const dist = Math.sqrt(dx * dx + dy * dy);
        const minDist = NODE_W * 0.6;
        if (dist < minDist && dist > 0) {
          const push = (minDist - dist) / 2;
          const nx = (dx / dist) * push;
          const ny = (dy / dist) * push;
          layout.set(idA, { ...nodeA, x: nodeA.x - nx, y: nodeA.y - ny });
          layout.set(idB, { ...nodeB, x: nodeB.x + nx, y: nodeB.y + ny });
        }
      }
    }
  }

  return layout;
}

// ── Block Node Card ──

function BlockNodeCard({
  block,
  noteTitle,
  outgoingCount,
  incomingCount,
  isSelected,
  isHighlighted,
  isFaded,
  position,
  onSelect,
  onDoubleClick,
  onHover,
  onLeave,
  onRefCountClick,
}: {
  block: NoteBlockRow;
  noteTitle?: string;
  outgoingCount: number;
  incomingCount: number;
  isSelected: boolean;
  isHighlighted: boolean;
  isFaded: boolean;
  position: { x: number; y: number };
  onSelect: () => void;
  onDoubleClick: () => void;
  onHover: () => void;
  onLeave: () => void;
  onRefCountClick: (type: 'incoming' | 'outgoing') => void;
}) {
  const typeColor = BLOCK_TYPE_COLORS[block.block_type] ?? 'bg-gray-500/15 text-gray-400 border-gray-500/30';
  const typeBorder = BLOCK_TYPE_BORDER[block.block_type] ?? 'border-l-gray-500';

  return (
    <div
      className={cn(
        'absolute rounded-lg border border-border bg-card shadow-md transition-all duration-150 select-none overflow-hidden cursor-grab active:cursor-grabbing',
        typeBorder,
        'border-l-2',
        isSelected && 'ring-2 ring-primary shadow-lg z-[60]',
        isHighlighted && !isSelected && 'ring-1 ring-primary/40 shadow-lg z-[50]',
        isFaded && !isHighlighted && 'opacity-25 z-[5]',
        !isSelected && !isHighlighted && !isFaded && 'z-[10]',
      )}
      style={{
        left: position.x,
        top: position.y,
        width: NODE_W,
        transform: 'translate(0, 0)',
      }}
      onClick={(e) => { e.stopPropagation(); onSelect(); }}
      onDoubleClick={(e) => { e.stopPropagation(); onDoubleClick(); }}
      onMouseEnter={onHover}
      onMouseLeave={onLeave}
    >
      {/* Type badge row */}
      <div className="flex items-center gap-1.5 px-2.5 py-1.5 border-b border-border/40 bg-muted/20">
        <Badge variant="outline" className={cn('text-[10px] px-1.5 py-0 font-semibold border', typeColor)}>
          {block.block_type}
        </Badge>
        <span className="text-[9px] text-muted-foreground/50 font-mono ml-auto">
          {shortId(block.id)}
        </span>
      </div>

      {/* Content preview */}
      <div className="px-2.5 py-2 min-h-[40px] flex flex-col justify-center">
        {noteTitle && (
          <p className="text-[10px] text-muted-foreground/70 truncate mb-0.5 leading-tight">
            {noteTitle}
          </p>
        )}
        <p className="text-xs leading-relaxed line-clamp-2 break-words">
          {block.content ? truncate(block.content, 80) : <span className="italic text-muted-foreground/40">(empty)</span>}
        </p>
      </div>

      {/* Ref count badges */}
      <div className="flex items-center gap-1.5 px-2.5 pb-1.5">
        {outgoingCount > 0 && (
          <button
            className="text-[10px] px-1.5 py-0.5 rounded-full bg-blue-500/10 text-blue-400 border border-blue-500/20 hover:bg-blue-500/20 transition-colors leading-tight"
            onClick={(e) => { e.stopPropagation(); onRefCountClick('outgoing'); }}
            title={`${outgoingCount} outgoing reference${outgoingCount > 1 ? 's' : ''}`}
          >
            →{outgoingCount}
          </button>
        )}
        {incomingCount > 0 && (
          <button
            className="text-[10px] px-1.5 py-0.5 rounded-full bg-green-500/10 text-green-400 border border-green-500/20 hover:bg-green-500/20 transition-colors leading-tight"
            onClick={(e) => { e.stopPropagation(); onRefCountClick('incoming'); }}
            title={`${incomingCount} incoming reference${incomingCount > 1 ? 's' : ''}`}
          >
            ←{incomingCount}
          </button>
        )}
        {outgoingCount === 0 && incomingCount === 0 && (
          <span className="text-[9px] text-muted-foreground/30 italic px-1">no refs</span>
        )}
      </div>
    </div>
  );
}

// ── Main Component ──

export default function BlockGraph() {
  const [, navigate] = useLocation();
  const containerRef = useRef<HTMLDivElement>(null);
  const dragRef = useRef<{
    blockId: string;
    startX: number;
    startY: number;
    origX: number;
    origY: number;
    moved: boolean;
  } | null>(null);

  // Data
  const { data: notes, loading: notesLoading } = useTable<NoteRow>('note');
  const { data: blocks, loading: blocksLoading } = useTable<NoteBlockRow>('note_block');
  const { data: refs, loading: refsLoading } = useTable<BlockReferenceRow>('block_reference');

  // UI state
  const [selectedBlockId, setSelectedBlockId] = useState<string | null>(null);
  const [hoveredBlockId, setHoveredBlockId] = useState<string | null>(null);
  const [filterMode, setFilterMode] = useState<'none' | 'incoming' | 'outgoing'>('none');
  const [filterBlockId, setFilterBlockId] = useState<string | null>(null);

  // Filter controls
  const [searchQuery, setSearchQuery] = useState('');
  const [showIsolates, setShowIsolates] = useState(false);
  const [showEmbeds, setShowEmbeds] = useState(true);
  const [showWikiLinks, setShowWikiLinks] = useState(true);
  const [typeFilters, setTypeFilters] = useState<Set<string>>(new Set(['heading', 'list', 'todo', 'quote', 'code']));
  const [showFilterBar, setShowFilterBar] = useState(true);

  // Drag state (kept in ref for performance)
  const [layoutPositions, setLayoutPositions] = useState<Map<string, LayoutNode>>(new Map());

  // ── Derived maps ──

  const noteMap = useMemo(() => {
    const m = new Map<string, NoteRow>();
    if (notes) for (const n of notes) m.set(n.id, n);
    return m;
  }, [notes]);

  const blockMap = useMemo(() => {
    const m = new Map<string, NoteBlockRow>();
    if (blocks) for (const b of blocks) m.set(b.id, b);
    return m;
  }, [blocks]);

  // Connections: blockId → set of connected block ids
  const forwardConnections = useMemo(() => {
    const m = new Map<string, Set<string>>();
    if (!refs) return m;
    for (const r of refs) {
      // Filter by ref type
      if (!showWikiLinks && r.ref_type === 'wiki_link') continue;
      if (!showEmbeds && r.ref_type === 'embed') continue;

      if (!m.has(r.source_block_id)) m.set(r.source_block_id, new Set());
      m.get(r.source_block_id)!.add(r.target_block_id);
    }
    return m;
  }, [refs, showWikiLinks, showEmbeds]);

  const backwardConnections = useMemo(() => {
    const m = new Map<string, Set<string>>();
    if (!refs) return m;
    for (const r of refs) {
      if (!showWikiLinks && r.ref_type === 'wiki_link') continue;
      if (!showEmbeds && r.ref_type === 'embed') continue;

      if (!m.has(r.target_block_id)) m.set(r.target_block_id, new Set());
      m.get(r.target_block_id)!.add(r.source_block_id);
    }
    return m;
  }, [refs, showWikiLinks, showEmbeds]);

  // Combined connections (undirected for layout)
  const allConnections = useMemo(() => {
    const m = new Map<string, Set<string>>();
    const add = (a: string, b: string) => {
      if (!m.has(a)) m.set(a, new Set());
      m.get(a)!.add(b);
    };
    if (!refs) return m;
    for (const r of refs) {
      if (!showWikiLinks && r.ref_type === 'wiki_link') continue;
      if (!showEmbeds && r.ref_type === 'embed') continue;
      add(r.source_block_id, r.target_block_id);
      add(r.target_block_id, r.source_block_id);
    }
    return m;
  }, [refs, showWikiLinks, showEmbeds]);

  // Compute outgoing/incoming counts per block
  const outgoingCounts = useMemo(() => {
    const m = new Map<string, number>();
    if (!refs) return m;
    for (const r of refs) {
      if (!showWikiLinks && r.ref_type === 'wiki_link') continue;
      if (!showEmbeds && r.ref_type === 'embed') continue;
      m.set(r.source_block_id, (m.get(r.source_block_id) || 0) + 1);
    }
    return m;
  }, [refs, showWikiLinks, showEmbeds]);

  const incomingCounts = useMemo(() => {
    const m = new Map<string, number>();
    if (!refs) return m;
    for (const r of refs) {
      if (!showWikiLinks && r.ref_type === 'wiki_link') continue;
      if (!showEmbeds && r.ref_type === 'embed') continue;
      m.set(r.target_block_id, (m.get(r.target_block_id) || 0) + 1);
    }
    return m;
  }, [refs, showWikiLinks, showEmbeds]);

  // ── Filtered blocks ──

  const filteredBlocks = useMemo(() => {
    if (!blocks) return [];
    let result = blocks.filter(b => b.is_active !== false);

    // Filter by type
    result = result.filter(b => typeFilters.has(b.block_type));

    // Search by content
    if (searchQuery.trim()) {
      const q = searchQuery.toLowerCase();
      result = result.filter(b =>
        (b.content && b.content.toLowerCase().includes(q)) ||
        shortId(b.id).toLowerCase().includes(q)
      );
    }

    // Filter mode: show only blocks connected to the filtered block
    if (filterMode !== 'none' && filterBlockId) {
      const connected = new Set<string>();
      if (filterMode === 'outgoing') {
        const out = forwardConnections.get(filterBlockId);
        if (out) for (const id of out) connected.add(id);
        connected.add(filterBlockId); // include the block itself
      } else {
        const inc = backwardConnections.get(filterBlockId);
        if (inc) for (const id of inc) connected.add(id);
        connected.add(filterBlockId);
      }
      result = result.filter(b => connected.has(b.id));
    }

    // Show isolates toggle
    if (!showIsolates) {
      result = result.filter(b => {
        const out = outgoingCounts.get(b.id) || 0;
        const inc = incomingCounts.get(b.id) || 0;
        return out > 0 || inc > 0;
      });
    }

    return result;
  }, [blocks, typeFilters, searchQuery, filterMode, filterBlockId, showIsolates, forwardConnections, backwardConnections, outgoingCounts, incomingCounts]);

  // ── Edges (for SVG lines) ──

  const visibleEdges = useMemo(() => {
    const visibleIds = new Set(filteredBlocks.map(b => b.id));
    const edges: Array<{ source: string; target: string; refType: string }> = [];
    const seen = new Set<string>();
    if (!refs) return edges;
    for (const r of refs) {
      // Apply the same ref-type filtering
      if (!showWikiLinks && r.ref_type === 'wiki_link') continue;
      if (!showEmbeds && r.ref_type === 'embed') continue;

      if (visibleIds.has(r.source_block_id) && visibleIds.has(r.target_block_id)) {
        const key = [r.source_block_id, r.target_block_id].sort().join('::');
        if (!seen.has(key)) {
          seen.add(key);
          edges.push({ source: r.source_block_id, target: r.target_block_id, refType: r.ref_type });
        }
      }
    }
    return edges;
  }, [refs, filteredBlocks, showWikiLinks, showEmbeds]);

  // ── Compute layout ──

  useEffect(() => {
    const blockIds = new Set(filteredBlocks.map(b => b.id));
    const newLayout = computeLayout(blockIds, allConnections);
    setLayoutPositions(newLayout);
  }, [filteredBlocks, allConnections]);

  // ── Stats ──

  const stats = useMemo(() => {
    const allNotes = new Map<string, boolean>();
    if (blocks) {
      for (const b of blocks) {
        if (b.note_id) allNotes.set(b.note_id, true);
      }
    }
    return {
      blockCount: filteredBlocks.length,
      refCount: visibleEdges.length,
      noteCount: allNotes.size,
    };
  }, [filteredBlocks, visibleEdges, blocks]);

  // ── Selected block details ──

  const selectedBlock = useMemo(() => {
    if (!selectedBlockId || !blockMap) return null;
    return blockMap.get(selectedBlockId) ?? null;
  }, [selectedBlockId, blockMap]);

  const selectedBlockNote = useMemo(() => {
    if (!selectedBlock) return null;
    return noteMap.get(selectedBlock.note_id) ?? null;
  }, [selectedBlock, noteMap]);

  const selectedIncomingRefs = useMemo(() => {
    if (!selectedBlockId || !refs) return [];
    return refs.filter(r => {
      if (!showWikiLinks && r.ref_type === 'wiki_link') return false;
      if (!showEmbeds && r.ref_type === 'embed') return false;
      return r.target_block_id === selectedBlockId;
    });
  }, [selectedBlockId, refs, showWikiLinks, showEmbeds]);

  const selectedOutgoingRefs = useMemo(() => {
    if (!selectedBlockId || !refs) return [];
    return refs.filter(r => {
      if (!showWikiLinks && r.ref_type === 'wiki_link') return false;
      if (!showEmbeds && r.ref_type === 'embed') return false;
      return r.source_block_id === selectedBlockId;
    });
  }, [selectedBlockId, refs, showWikiLinks, showEmbeds]);

  // ── Drag handlers ──

  const handleMouseDown = useCallback((e: React.MouseEvent, blockId: string) => {
    // Only left click
    if (e.button !== 0) return;
    const pos = layoutPositions.get(blockId);
    if (!pos) return;

    e.preventDefault();
    e.stopPropagation();

    dragRef.current = {
      blockId,
      startX: e.clientX,
      startY: e.clientY,
      origX: pos.x,
      origY: pos.y,
      moved: false,
    };

    const handleMouseMove = (me: MouseEvent) => {
      if (!dragRef.current) return;
      const dx = me.clientX - dragRef.current.startX;
      const dy = me.clientY - dragRef.current.startY;
      if (Math.abs(dx) > 3 || Math.abs(dy) > 3) {
        dragRef.current.moved = true;
      }
      setLayoutPositions(prev => {
        const next = new Map(prev);
        next.set(dragRef.current!.blockId, {
          blockId: dragRef.current!.blockId,
          x: dragRef.current!.origX + dx,
          y: dragRef.current!.origY + dy,
        });
        return next;
      });
    };

    const handleMouseUp = () => {
      document.removeEventListener('mousemove', handleMouseMove);
      document.removeEventListener('mouseup', handleMouseUp);

      if (dragRef.current && !dragRef.current.moved) {
        // Was a click, not a drag — handled by onClick on the card
      }
      dragRef.current = null;
    };

    document.addEventListener('mousemove', handleMouseMove);
    document.addEventListener('mouseup', handleMouseUp);
  }, [layoutPositions]);

  // ── Zoom to fit ──

  const zoomToFit = useCallback(() => {
    if (!containerRef.current) return;
    const container = containerRef.current;
    const nodes = [...layoutPositions.values()];
    if (nodes.length === 0) return;

    let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity;
    for (const n of nodes) {
      minX = Math.min(minX, n.x);
      minY = Math.min(minY, n.y);
      maxX = Math.max(maxX, n.x + NODE_W);
      maxY = Math.max(maxY, n.y + NODE_H);
    }

    const pad = 60;
    minX -= pad;
    minY -= pad;
    maxX += pad;
    maxY += pad;

    const cw = container.clientWidth;
    const ch = container.clientHeight;
    const scaleX = cw / (maxX - minX);
    const scaleY = ch / (maxY - minY);
    const scale = Math.min(scaleX, scaleY, 1.5);

    container.scrollLeft = (minX + (maxX - minX) / 2) * scale - cw / 2 + (container.scrollWidth - cw) * 0;
    // Just a rough scroll — we'll transform via CSS instead
    // Actually, let's just adjust container scroll
  }, [layoutPositions]);

  // ── Handlers ──

  const toggleTypeFilter = (type: string) => {
    setTypeFilters(prev => {
      const next = new Set(prev);
      if (next.has(type)) next.delete(type);
      else next.add(type);
      return next;
    });
  };

  const clearSelection = useCallback(() => {
    setSelectedBlockId(null);
    setFilterMode('none');
    setFilterBlockId(null);
  }, []);

  const handleBlockSelect = useCallback((blockId: string) => {
    if (selectedBlockId === blockId) {
      clearSelection();
    } else {
      setSelectedBlockId(blockId);
      setFilterMode('none');
      setFilterBlockId(null);
    }
  }, [selectedBlockId, clearSelection]);

  const handleRefCountClick = useCallback((blockId: string, type: 'incoming' | 'outgoing') => {
    setFilterBlockId(blockId);
    setFilterMode(type);
    setSelectedBlockId(blockId);
  }, []);

  const handleDoubleClick = useCallback((blockId: string) => {
    const block = blockMap.get(blockId);
    if (block?.note_id) {
      navigate(`/notes/${block.note_id}`);
    }
  }, [blockMap, navigate]);

  // ── Clear filter on background click ──

  const handleBackgroundClick = useCallback(() => {
    clearSelection();
  }, [clearSelection]);

  // ── Edge highlight sets ──

  const highlightSet = useMemo(() => {
    if (!hoveredBlockId && !selectedBlockId) return null;
    const id = hoveredBlockId || selectedBlockId;
    if (!id) return null;
    const set = new Set<string>();
    set.add(id);
    const out = forwardConnections.get(id);
    if (out) for (const c of out) set.add(c);
    const inc = backwardConnections.get(id);
    if (inc) for (const c of inc) set.add(c);
    return set;
  }, [hoveredBlockId, selectedBlockId, forwardConnections, backwardConnections]);

  // ── Loading state ──

  const isLoading = notesLoading || blocksLoading || refsLoading;

  // ── Render ──

  return (
    <div className="h-full flex flex-col">
      {/* ── Header + Filter Bar ── */}
      <div className="flex items-center gap-3 px-6 py-3 border-b border-border shrink-0 flex-wrap">
        <Button variant="ghost" size="icon" onClick={() => navigate('/notes')}>
          <ArrowLeft className="h-4 w-4" />
        </Button>
        <div className="flex-1 min-w-0">
          <h1 className="text-lg font-semibold">Block Graph</h1>
          <p className="text-xs text-muted-foreground">
            {isLoading
              ? 'Loading…'
              : `${stats.blockCount} blocks, ${stats.refCount} references, ${stats.noteCount} notes`
            }
          </p>
        </div>

        {/* Stats */}
        <div className="flex items-center gap-2">
          <Badge variant="outline" className="text-xs gap-1">
            <MessageSquare className="h-3 w-3" />
            {stats.blockCount}
          </Badge>
          <Badge variant="outline" className="text-xs gap-1">
            <Share2 className="h-3 w-3" />
            {stats.refCount}
          </Badge>
          <Badge variant="outline" className="text-xs gap-1">
            <FileText className="h-3 w-3" />
            {stats.noteCount}
          </Badge>
        </div>

        {/* Zoom to fit */}
        <Button variant="outline" size="sm" className="h-8" onClick={zoomToFit} title="Zoom to fit">
          <ZoomIn className="h-3.5 w-3.5" />
        </Button>

        {/* Toggle filter bar */}
        <Button
          variant={showFilterBar ? 'default' : 'outline'}
          size="sm"
          className="h-8"
          onClick={() => setShowFilterBar(v => !v)}
        >
          <Filter className="h-3.5 w-3.5" />
        </Button>
      </div>

      {/* ── Filter bar ── */}
      {showFilterBar && (
        <div className="px-6 py-2 border-b border-border bg-muted/10">
          <div className="flex flex-wrap items-center gap-3">
            {/* Search */}
            <div className="relative min-w-[160px]">
              <Search className="absolute left-2 top-1/2 -translate-y-1/2 h-3.5 w-3.5 text-muted-foreground" />
              <Input
                placeholder="Search blocks…"
                className="pl-7 h-8 text-xs"
                value={searchQuery}
                onChange={e => setSearchQuery(e.target.value)}
              />
            </div>

            {/* Type filters */}
            <div className="flex items-center gap-1 flex-wrap">
              {['heading', 'list', 'todo', 'quote', 'code'].map(type => (
                <button
                  key={type}
                  className={cn(
                    'text-[10px] px-2 py-1 rounded-full border transition-colors',
                    typeFilters.has(type)
                      ? 'bg-primary/10 border-primary/30 text-primary'
                      : 'bg-muted/30 border-border text-muted-foreground/60 hover:text-foreground',
                  )}
                  onClick={() => toggleTypeFilter(type)}
                >
                  {type}
                </button>
              ))}
            </div>

            {/* Toggles */}
            <label className="flex items-center gap-1.5 text-xs text-muted-foreground cursor-pointer select-none">
              <input
                type="checkbox"
                checked={showIsolates}
                onChange={e => setShowIsolates(e.target.checked)}
                className="rounded"
              />
              Isolates
            </label>
            <label className="flex items-center gap-1.5 text-xs text-muted-foreground cursor-pointer select-none">
              <input
                type="checkbox"
                checked={showWikiLinks}
                onChange={e => setShowWikiLinks(e.target.checked)}
                className="rounded"
              />
              ((wiki-link))
            </label>
            <label className="flex items-center gap-1.5 text-xs text-muted-foreground cursor-pointer select-none">
              <input
                type="checkbox"
                checked={showEmbeds}
                onChange={e => setShowEmbeds(e.target.checked)}
                className="rounded"
              />
              {'{{embed}}'}
            </label>

            {/* Filter mode badge */}
            {filterMode !== 'none' && filterBlockId && (
              <Badge variant="secondary" className="text-[10px] gap-1">
                {filterMode === 'outgoing' ? '→ Outgoing' : '← Incoming'}
                <button onClick={() => { setFilterMode('none'); setFilterBlockId(null); }}>
                  <X className="h-3 w-3" />
                </button>
              </Badge>
            )}
          </div>
        </div>
      )}

      {/* ── Main Content ── */}
      <div className="flex-1 relative overflow-hidden">
        {isLoading && (
          <div className="absolute inset-0 flex items-center justify-center bg-background/80 z-[100]">
            <div className="flex flex-col items-center gap-3">
              <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
              <p className="text-sm text-muted-foreground">Loading block data…</p>
            </div>
          </div>
        )}

        {!isLoading && stats.blockCount === 0 && (
          <div className="absolute inset-0 flex flex-col items-center justify-center text-muted-foreground">
            <Share2 className="h-12 w-12 mb-3 opacity-25" />
            <p className="text-lg font-medium">No block refs yet</p>
            <p className="text-sm mt-1 max-w-md text-center">
              {searchQuery
                ? 'Try a different search term or check your filters.'
                : 'Create blocks with ((block-id)) syntax in notes to see them here.'}
            </p>
          </div>
        )}

        {!isLoading && stats.blockCount > 0 && (
          <div
            ref={containerRef}
            className="w-full h-full overflow-auto relative"
            onClick={handleBackgroundClick}
          >
            {/* SVG overlay for connection lines */}
            <svg
              className="absolute inset-0 pointer-events-none z-[1]"
              style={{ minWidth: 2000, minHeight: 2000 }}
            >
              {visibleEdges.map((edge, i) => {
                const srcPos = layoutPositions.get(edge.source);
                const tgtPos = layoutPositions.get(edge.target);
                if (!srcPos || !tgtPos) return null;
                const x1 = srcPos.x + NODE_W / 2;
                const y1 = srcPos.y + NODE_H / 2;
                const x2 = tgtPos.x + NODE_W / 2;
                const y2 = tgtPos.y + NODE_H / 2;
                const highlighted = highlightSet
                  ? (highlightSet.has(edge.source) && highlightSet.has(edge.target))
                  : true;
                const faded = highlightSet && !highlighted;
                return (
                  <line
                    key={i}
                    x1={x1}
                    y1={y1}
                    x2={x2}
                    y2={y2}
                    stroke={edge.refType === 'embed' ? '#a78bfa' : '#60a5fa'}
                    strokeWidth={highlighted ? 2 : 0.5}
                    strokeOpacity={faded ? 0.1 : highlighted ? 0.6 : 0.2}
                    strokeDasharray={edge.refType === 'embed' ? '4 3' : 'none'}
                    className="transition-all duration-200"
                  />
                );
              })}
            </svg>

            {/* Block nodes */}
            {filteredBlocks.map(block => {
              const pos = layoutPositions.get(block.id);
              if (!pos) return null;

              const note = noteMap.get(block.note_id);
              const outCount = outgoingCounts.get(block.id) || 0;
              const inCount = incomingCounts.get(block.id) || 0;
              const isSelected = selectedBlockId === block.id;
              const isHovered = hoveredBlockId === block.id;
              const isHighlighted = highlightSet ? highlightSet.has(block.id) : true;
              const isFaded = highlightSet ? !isHighlighted : false;

              return (
                <div
                  key={block.id}
                  onMouseDown={(e) => handleMouseDown(e, block.id)}
                  style={{ position: 'absolute', left: 0, top: 0, zIndex: 0, pointerEvents: 'none' }}
                >
                  <div style={{ pointerEvents: 'auto' }}>
                    <BlockNodeCard
                      block={block}
                      noteTitle={note?.title}
                      outgoingCount={outCount}
                      incomingCount={inCount}
                      isSelected={isSelected}
                      isHighlighted={isHighlighted || isHovered}
                      isFaded={isFaded}
                      position={pos}
                      onSelect={() => handleBlockSelect(block.id)}
                      onDoubleClick={() => handleDoubleClick(block.id)}
                      onHover={() => setHoveredBlockId(block.id)}
                      onLeave={() => setHoveredBlockId(null)}
                      onRefCountClick={(type) => handleRefCountClick(block.id, type)}
                    />
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </div>

      {/* ── Side Panel (selected block) ── */}
      {selectedBlock && (
        <div className="fixed right-0 top-0 bottom-0 w-[400px] max-w-[90vw] border-l border-border bg-card shadow-xl z-[200] overflow-y-auto">
          {/* Panel header */}
          <div className="sticky top-0 bg-card border-b border-border px-4 py-3 flex items-center gap-2 z-10">
            <Badge variant="outline" className={cn('text-xs', BLOCK_TYPE_COLORS[selectedBlock.block_type] ?? '')}>
              {selectedBlock.block_type}
            </Badge>
            <span className="text-xs font-mono text-muted-foreground ml-auto">{shortId(selectedBlock.id)}</span>
            <Button variant="ghost" size="icon" className="h-7 w-7" onClick={clearSelection}>
              <X className="h-4 w-4" />
            </Button>
          </div>

          <div className="p-4 space-y-4">
            {/* Parent note link */}
            {selectedBlockNote && (
              <div className="flex items-center gap-2">
                <FileText className="h-4 w-4 text-muted-foreground shrink-0" />
                <Link
                  href={`/notes/${selectedBlock.note_id}`}
                  className="text-sm text-primary hover:underline truncate"
                  onClick={(e) => { e.stopPropagation(); navigate(`/notes/${selectedBlock.note_id}`); }}
                >
                  {selectedBlockNote.title || '(untitled)'}
                </Link>
                <ExternalLink className="h-3 w-3 text-muted-foreground shrink-0" />
              </div>
            )}

            {/* Full content */}
            <div>
              <h4 className="text-xs font-semibold text-muted-foreground mb-2 uppercase tracking-wider">Content</h4>
              <div className="rounded-lg border border-border p-3 bg-muted/20 text-sm prose prose-sm prose-invert max-w-none">
                <MarkdownRenderer
                  content={selectedBlock.content || ''}
                  notes={notes || []}
                  currentNoteId={selectedBlock.note_id}
                  noteBlocks={blocks as any}
                />
              </div>
            </div>

            {/* Outgoing refs */}
            <div>
              <h4 className="text-xs font-semibold text-muted-foreground mb-2 uppercase tracking-wider flex items-center gap-1.5">
                <CornerDownRight className="h-3 w-3" />
                Outgoing Refs ({selectedOutgoingRefs.length})
              </h4>
              {selectedOutgoingRefs.length === 0 ? (
                <p className="text-xs text-muted-foreground/50 italic">No outgoing references</p>
              ) : (
                <div className="space-y-1.5">
                  {selectedOutgoingRefs.map(ref => {
                    const targetBlock = blockMap.get(ref.target_block_id);
                    const targetNote = targetBlock ? noteMap.get(targetBlock.note_id) : undefined;
                    return (
                      <div
                        key={ref.id}
                        className="flex items-start gap-2 p-2 rounded-md border border-border/50 bg-muted/10 cursor-pointer hover:bg-muted/20 transition-colors"
                        onClick={() => setSelectedBlockId(ref.target_block_id)}
                      >
                        <Badge variant="outline" className="text-[9px] px-1 py-0 mt-0.5 shrink-0">
                          {ref.ref_type}
                        </Badge>
                        <div className="min-w-0 flex-1">
                          <p className="text-xs truncate">
                            {targetBlock ? truncate(targetBlock.content, 60) : <span className="italic text-muted-foreground/50">missing block</span>}
                          </p>
                          {targetNote && (
                            <p className="text-[10px] text-muted-foreground truncate">{targetNote.title}</p>
                          )}
                        </div>
                      </div>
                    );
                  })}
                </div>
              )}
            </div>

            {/* Incoming refs */}
            <div>
              <h4 className="text-xs font-semibold text-muted-foreground mb-2 uppercase tracking-wider flex items-center gap-1.5">
                <CornerDownRight className="h-3 w-3 rotate-180" />
                Incoming Refs ({selectedIncomingRefs.length})
              </h4>
              {selectedIncomingRefs.length === 0 ? (
                <p className="text-xs text-muted-foreground/50 italic">No incoming references</p>
              ) : (
                <div className="space-y-1.5">
                  {selectedIncomingRefs.map(ref => {
                    const srcBlock = blockMap.get(ref.source_block_id);
                    const srcNote = srcBlock ? noteMap.get(srcBlock.note_id) : undefined;
                    return (
                      <div
                        key={ref.id}
                        className="flex items-start gap-2 p-2 rounded-md border border-border/50 bg-muted/10 cursor-pointer hover:bg-muted/20 transition-colors"
                        onClick={() => setSelectedBlockId(ref.source_block_id)}
                      >
                        <Badge variant="outline" className="text-[9px] px-1 py-0 mt-0.5 shrink-0">
                          {ref.ref_type}
                        </Badge>
                        <div className="min-w-0 flex-1">
                          <p className="text-xs truncate">
                            {srcBlock ? truncate(srcBlock.content, 60) : <span className="italic text-muted-foreground/50">missing block</span>}
                          </p>
                          {srcNote && (
                            <p className="text-[10px] text-muted-foreground truncate">{srcNote.title}</p>
                          )}
                        </div>
                      </div>
                    );
                  })}
                </div>
              )}
            </div>

            {/* Create ref placeholder */}
            <div className="border-t border-border pt-3">
              <Button
                variant="outline"
                size="sm"
                className="w-full text-xs"
                onClick={() => {
                  const ref = prompt('Enter block ID to reference:\n(e.g., abc123 or block-order-hex)');
                  if (ref && ref.trim()) {
                    alert(`Placeholder: copying ((ref)) syntax to clipboard\n((${ref.trim()}))`);
                    navigator.clipboard?.writeText(`((${ref.trim()}))`);
                  }
                }}
              >
                <Share2 className="h-3 w-3 mr-1.5" />
                Create Ref
              </Button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
