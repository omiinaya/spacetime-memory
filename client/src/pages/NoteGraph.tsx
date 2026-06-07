import { useEffect, useRef, useState } from 'react';
import { Network as VisNetwork } from 'vis-network';
import { DataSet } from 'vis-data';
import { useLocation } from 'wouter';
import { ArrowLeft, Loader2, AlertCircle, FileText } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { fetchNotesWithBacklinks } from '@/lib/spacetimedb';

export default function NoteGraph() {
  const [, navigate] = useLocation();
  const containerRef = useRef<HTMLDivElement>(null);
  const networkRef = useRef<VisNetwork | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [noteCount, setNoteCount] = useState(0);

  useEffect(() => {
    const load = async () => {
      try {
        const notes = await fetchNotesWithBacklinks();
        if (!notes || notes.length === 0) {
          setLoading(false);
          setNoteCount(0);
          return;
        }

        // eslint-disable-next-line @typescript-eslint/no-explicit-any
        const nodes = new DataSet<any>();
        // eslint-disable-next-line @typescript-eslint/no-explicit-any
        const edges = new DataSet<any>();

        notes.forEach((note: any) => {
          const count = parseInt(note.backlinkCount) || 0;
          const size = 15 + Math.min(count * 3, 30);
          nodes.add({
            id: note.id,
            label: (note.title || note.id.slice(0, 8)).slice(0, 30),
            title: `${note.title || 'Untitled'}\nBacklinks: ${count}\n${note.content?.slice(0, 100) || ''}`,
            value: size,
            color: count > 0
              ? { background: '#1e3a5f', border: '#3b82f6' }
              : { background: '#1f2937', border: '#6b7280' },
            shape: 'dot',
          });
        });

        const edgeSet = new Set<string>();
        notes.forEach((note: any) => {
          const links = note.outgoingLinks || '[]';
          let linkTitles: string[] = [];
          try { linkTitles = JSON.parse(links); } catch {}
          linkTitles.forEach((targetTitle: string) => {
            const target = notes.find((n: any) => n.title === targetTitle);
            if (target) {
              const edgeId = `${note.id}-${target.id}`;
              if (!edgeSet.has(edgeId)) {
                edgeSet.add(edgeId);
                edges.add({
                  id: edgeId,
                  from: note.id,
                  to: target.id,
                  color: '#4b5563',
                  width: 1,
                });
              }
            }
          });
        });

        setNoteCount(notes.length);

        if (containerRef.current) {
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
  }, []);

  return (
    <div className="h-full flex flex-col">
      <div className="flex items-center gap-3 px-6 py-3 border-b border-border shrink-0">
        <Button variant="ghost" size="icon" onClick={() => navigate('/notes')}>
          <ArrowLeft className="h-4 w-4" />
        </Button>
        <div>
          <h1 className="text-lg font-semibold">Note Graph</h1>
          <p className="text-xs text-muted-foreground">
            {loading ? 'Loading...' : `${noteCount} notes with wikilink connections`}
          </p>
        </div>
      </div>

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
            <p className="text-lg font-medium">No notes yet</p>
            <p className="text-sm mt-1">Create notes with [[wikilinks]] to see them here.</p>
          </div>
        )}

        {error && (
          <div className="absolute inset-0 flex flex-col items-center justify-center text-muted-foreground">
            <AlertCircle className="h-12 w-12 mb-3 text-red-500/50" />
            <p className="text-lg font-medium">Failed to load graph</p>
            <p className="text-sm mt-1 text-red-400/70">{error}</p>
          </div>
        )}

        <div ref={containerRef} className={`w-full h-full ${loading ? 'opacity-0' : 'opacity-100'} transition-opacity duration-300`} />
      </div>
    </div>
  );
}
