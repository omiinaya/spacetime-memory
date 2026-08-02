import { useEffect, useRef, useState, useMemo } from 'react';
import { Network as VisNetwork } from 'vis-network';
import { DataSet } from 'vis-data';
import { useLocation } from 'wouter';
import {
  ArrowLeft, Loader2, AlertCircle, FileText, Search,
  SlidersHorizontal, Network,
} from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Badge } from '@/components/ui/badge';
import { useTable } from '@/lib/useReactiveDb';

interface NoteRow {
  id: string;
  title: string;
  content: string;
  note_date: string;
  backlink_count: number;
  block_ref_count: number;
  updated_at: number;
  is_active: boolean;
}

interface NoteBacklinkRow {
  id: string;
  source_note_id: string;
  target_note_id: string;
}

export default function NoteGraph() {
  const [, navigate] = useLocation();
  const containerRef = useRef<HTMLDivElement>(null);
  const networkRef = useRef<VisNetwork | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [noteCount, setNoteCount] = useState(0);
  const [edgeCount, setEdgeCount] = useState(0);

  // Filters
  const [searchQuery, setSearchQuery] = useState('');
  const [minLinks, setMinLinks] = useState(0);
  const [showOrphans, setShowOrphans] = useState(true);
  const [showFilter, setShowFilter] = useState(false);

  const { data: notes } = useTable<NoteRow>('note');
  const { data: backlinks } = useTable<NoteBacklinkRow>('note_backlink');

  const activeNotes = useMemo(() =>
    (notes || []).filter((n: NoteRow) => n.is_active),
    [notes]
  );

  const backlinkMap = useMemo(() => {
    const map = new Map<string, number>();
    if (backlinks) {
      for (const bl of backlinks) {
        map.set(bl.target_note_id, (map.get(bl.target_note_id) || 0) + 1);
      }
    }
    return map;
  }, [backlinks]);

  // Search/filter logic
  const filteredNotes = useMemo(() => {
    let result = activeNotes;

    // Filter by search query
    if (searchQuery.trim()) {
      const q = searchQuery.toLowerCase();
      result = result.filter((n: NoteRow) =>
        (n.title && n.title.toLowerCase().includes(q)) ||
        (n.content && n.content.toLowerCase().includes(q)) ||
        (n.id && n.id.toLowerCase().includes(q))
      );
    }

    // Filter by minimum backlinks
    if (minLinks > 0) {
      result = result.filter((n: NoteRow) =>
        (backlinkMap.get(n.id) || 0) >= minLinks
      );
    }

    // Filter orphans
    if (!showOrphans) {
      result = result.filter((n: NoteRow) =>
        (backlinkMap.get(n.id) || 0) > 0
      );
    }

    return result;
  }, [activeNotes, searchQuery, minLinks, showOrphans, backlinkMap]);

  // Filter edges that connect visible nodes
  const filteredEdges = useMemo(() => {
    const nodeIds = new Set(filteredNotes.map((n: NoteRow) => n.id));
    const edges: Array<{ id: string; from: string; to: string }> = [];
    const edgeSet = new Set<string>();

    if (backlinks) {
      for (const bl of backlinks) {
        if (nodeIds.has(bl.source_note_id) && nodeIds.has(bl.target_note_id)) {
          const edgeId = `${bl.source_note_id}->${bl.target_note_id}`;
          if (!edgeSet.has(edgeId)) {
            edgeSet.add(edgeId);
            edges.push({
              id: edgeId,
              from: bl.source_note_id,
              to: bl.target_note_id,
            });
          }
        }
      }
    }

    return edges;
  }, [filteredNotes, backlinks]);

  useEffect(() => {
    const load = async () => {
      try {
        if (!filteredNotes || filteredNotes.length === 0) {
          setLoading(false);
          setNoteCount(0);
          setEdgeCount(0);
          return;
        }

        // eslint-disable-next-line @typescript-eslint/no-explicit-any
        const nodes = new DataSet<any>();
        // eslint-disable-next-line @typescript-eslint/no-explicit-any
        const edges = new DataSet<any>();

        const maxBacklinks = Math.max(
          1,
          ...filteredNotes.map((n: NoteRow) => backlinkMap.get(n.id) || 0)
        );

        filteredNotes.forEach((note: NoteRow) => {
          const blCount = backlinkMap.get(note.id) || 0;
          // Size: base 15 + up to 35 additional based on backlink ratio
          const size = 15 + Math.min(Math.round((blCount / maxBacklinks) * 35), 35);
          nodes.add({
            id: note.id,
            label: (note.title || note.id.slice(0, 8)).slice(0, 30),
            title: `${note.title || 'Untitled'}\nBacklinks: ${blCount}\nBlock refs: ${note.block_ref_count || 0}\nID: ${note.id.slice(0, 12)}...`,
            value: size,
            color: blCount > 0
              ? { background: '#1e3a5f', border: '#3b82f6' }
              : { background: '#1f2937', border: '#6b7280' },
            shape: 'dot',
            borderWidth: blCount > 0 ? 2 : 1,
          });
        });

        const edgeSet = new Set<string>();
        filteredEdges.forEach(edge => {
          if (!edgeSet.has(edge.id)) {
            edgeSet.add(edge.id);
            edges.add({
              id: edge.id,
              from: edge.from,
              to: edge.to,
              color: '#4b5563',
              width: 1,
              smooth: {
                enabled: true,
                type: 'curvedCW',
                roundness: 0.1,
              },
            });
          }
        });

        setNoteCount(filteredNotes.length);
        setEdgeCount(edges.length);

        if (containerRef.current) {
          // Destroy previous network
          if (networkRef.current) {
            networkRef.current.destroy();
            networkRef.current = null;
          }

          // eslint-disable-next-line @typescript-eslint/no-explicit-any
          const visOptions: any = {
            nodes: {
              font: { color: '#e5e7eb', size: 12 },
              borderWidth: 2,
            },
            edges: {
              smooth: {
                enabled: true,
                type: 'curvedCW',
                roundness: 0.2,
              },
            },
            physics: {
              solver: 'forceAtlas2Based',
              forceAtlas2Based: {
                gravitationalConstant: -60,
                centralGravity: 0.005,
                springLength: 180,
                springConstant: 0.02,
                damping: 0.4,
              },
              stabilization: { iterations: 100 },
            },
            interaction: {
              hover: true,
              tooltipDelay: 200,
              zoomView: true,
              dragView: true,
            },
            layout: {
              improvedLayout: true,
            },
          };

          networkRef.current = new VisNetwork(
            containerRef.current,
            { nodes: nodes as any, edges: edges as any },
            visOptions
          );

          networkRef.current.on('click', (params: any) => {
            if (params.nodes.length > 0) {
              navigate(`/notes/${params.nodes[0]}`);
            }
          });
        }

        setLoading(false);
      } catch (e: any) {
        setError(e.message || 'Failed to load note graph');
        setLoading(false);
      }
    };

    load();

    return () => {
      if (networkRef.current) {
        networkRef.current.destroy();
        networkRef.current = null;
      }
    };
  }, [filteredNotes, filteredEdges, navigate]);

  return (
    <div className="h-full flex flex-col">
      <div className="flex items-center gap-3 px-6 py-3 border-b border-border shrink-0">
        <Button variant="ghost" size="icon" onClick={() => navigate('/notes')}>
          <ArrowLeft className="h-4 w-4" />
        </Button>
        <div className="flex-1">
          <h1 className="text-lg font-semibold">Note Graph</h1>
          <p className="text-xs text-muted-foreground">
            {loading ? 'Loading...' : `${noteCount} notes, ${edgeCount} connections`}
          </p>
        </div>
        <div className="flex items-center gap-2">
          {/* Search */}
          <div className="relative">
            <Search className="absolute left-2 top-1/2 -translate-y-1/2 h-3.5 w-3.5 text-muted-foreground" />
            <Input
              placeholder="Search notes..."
              className="pl-7 h-8 w-48 text-xs"
              value={searchQuery}
              onChange={e => setSearchQuery(e.target.value)}
            />
          </div>
          {/* Filter toggle */}
          <Button
            variant={showFilter ? 'default' : 'outline'}
            size="sm"
            className="h-8"
            onClick={() => setShowFilter(!showFilter)}
          >
            <SlidersHorizontal className="h-3.5 w-3.5" />
          </Button>
          {/* Stats badge */}
          <Badge variant="outline" className="text-xs">
            <Network className="h-3 w-3 mr-1" />
            {noteCount}
          </Badge>
        </div>
      </div>

      {/* Filter bar */}
      {showFilter && (
        <div className="px-6 py-2 border-b border-border bg-muted/20">
          <div className="flex items-center gap-4 flex-wrap">
            <label className="flex items-center gap-2 text-xs text-muted-foreground">
              <input
                type="checkbox"
                checked={showOrphans}
                onChange={e => setShowOrphans(e.target.checked)}
                className="rounded"
              />
              Show orphans (no links)
            </label>
            <label className="flex items-center gap-2 text-xs text-muted-foreground">
              <SlidersHorizontal className="h-3 w-3" />
              Min links:
              <select
                className="bg-background border border-border rounded px-1 py-0.5 text-xs"
                value={minLinks}
                onChange={e => setMinLinks(Number(e.target.value))}
              >
                <option value={0}>Any</option>
                <option value={1}>1+</option>
                <option value={3}>3+</option>
                <option value={5}>5+</option>
                <option value={10}>10+</option>
              </select>
            </label>
            <span className="text-[10px] text-muted-foreground/50 ml-auto">
              Click a node to open its note
            </span>
          </div>
        </div>
      )}

      <div className="flex-1 relative">
        {loading && (
          <div className="absolute inset-0 flex items-center justify-center bg-background/80 z-10">
            <div className="flex flex-col items-center gap-2">
              <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
              <p className="text-sm text-muted-foreground">Building graph layout...</p>
            </div>
          </div>
        )}

        {!loading && noteCount === 0 && !error && (
          <div className="absolute inset-0 flex flex-col items-center justify-center text-muted-foreground">
            <FileText className="h-12 w-12 mb-3 opacity-30" />
            <p className="text-lg font-medium">No notes match</p>
            <p className="text-sm mt-1">
              {searchQuery
                ? 'Try a different search term.'
                : 'Create notes with [[wikilinks]] to see them here.'}
            </p>
          </div>
        )}

        {error && (
          <div className="absolute inset-0 flex flex-col items-center justify-center text-muted-foreground">
            <AlertCircle className="h-12 w-12 mb-3 text-red-500/50" />
            <p className="text-lg font-medium">Failed to load graph</p>
            <p className="text-sm mt-1 text-red-400/70">{error}</p>
          </div>
        )}

        <div
          ref={containerRef}
          className={`w-full h-full ${loading ? 'opacity-0' : 'opacity-100'} transition-opacity duration-300`}
        />
      </div>
    </div>
  );
}
