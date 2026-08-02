import { useState, useMemo } from 'react';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { Skeleton } from '@/components/ui/skeleton';
import { useTable } from '@/lib/useReactiveDb';
import { MarkdownRenderer } from '@/components/MarkdownRenderer';
import {
  Route, ArrowLeft, ArrowRight, Play, Compass,
  FileText, AlertCircle,
} from 'lucide-react';

interface TourRow {
  id: string;
  workspace_id: string;
  title: string;
  description: string;
  created_at: number;
}

interface TourStopRow {
  id: string;
  tour_id: string;
  node_id: string;
  stop_order: number;
  heading: string;
  description: string;
  created_at: number;
}

interface NoteRow {
  id: string;
  title: string;
  content: string;
}

export default function Tours() {
  const { data: tours, loading, error } = useTable<TourRow>('tour');
  const { data: stops } = useTable<TourStopRow>('tour_stop');
  const { data: notes } = useTable<NoteRow>('note');

  const [activeTourId, setActiveTourId] = useState<string | null>(null);
  const [currentStop, setCurrentStop] = useState(0);

  const activeTour = useMemo(() => {
    if (!activeTourId) return null;
    return tours.find((t: TourRow) => t.id === activeTourId) ?? null;
  }, [tours, activeTourId]);

  const tourStops = useMemo(() => {
    if (!activeTourId || !stops) return [];
    return stops
      .filter((s: TourStopRow) => s.tour_id === activeTourId)
      .sort((a: TourStopRow, b: TourStopRow) => a.stop_order - b.stop_order);
  }, [stops, activeTourId]);

  const currentStopData = tourStops[currentStop] || null;

  // Find note title/content for this stop's node
  const stopNote = useMemo(() => {
    if (!currentStopData || !notes) return null;
    return notes.find((n: NoteRow) => n.id === currentStopData.node_id) ?? null;
  }, [currentStopData, notes]);

  if (activeTour) {
    return (
      <div className="space-y-6">
        {/* Tour header */}
        <div className="flex items-center justify-between">
          <div>
            <div className="flex items-center gap-2">
              <Button variant="ghost" size="icon" onClick={() => { setActiveTourId(null); setCurrentStop(0); }}>
                <ArrowLeft className="h-4 w-4" />
              </Button>
              <h1 className="text-2xl font-bold tracking-tight">{activeTour.title}</h1>
            </div>
            <p className="text-muted-foreground ml-10">{activeTour.description}</p>
          </div>
          <div className="flex items-center gap-2">
            <Badge variant="outline">
              {currentStop + 1} / {tourStops.length}
            </Badge>
          </div>
        </div>

        {tourStops.length === 0 ? (
          <Card>
            <CardContent className="py-12 text-center text-muted-foreground">
              <Route className="h-8 w-8 mx-auto mb-2 opacity-30" />
              <p>No stops in this tour yet.</p>
            </CardContent>
          </Card>
        ) : (
          <>
            {/* Progress bar */}
            <div className="w-full bg-muted rounded-full h-1.5">
              <div
                className="bg-primary h-1.5 rounded-full transition-all duration-300"
                style={{ width: `${((currentStop + 1) / tourStops.length) * 100}%` }}
              />
            </div>

            {/* Current stop */}
            <Card>
              <CardHeader>
                <CardTitle className="flex items-center gap-2 text-lg">
                  <Compass className="h-5 w-5 text-primary" />
                  {currentStopData.heading || `Stop ${currentStop + 1}`}
                </CardTitle>
              </CardHeader>
              <CardContent className="space-y-4">
                {currentStopData.description && (
                  <div className="prose prose-sm prose-invert max-w-none text-muted-foreground">
                    <MarkdownRenderer
                      content={currentStopData.description}
                      notes={notes}
                    />
                  </div>
                )}

                {stopNote && (
                  <Card className="bg-muted/30 border-l-2 border-l-primary/40">
                    <CardContent className="p-4">
                      <div className="flex items-center gap-2 text-xs text-muted-foreground mb-2">
                        <FileText className="h-3 w-3" />
                        <span className="font-medium">{stopNote.title}</span>
                      </div>
                      <div className="prose prose-sm prose-invert max-w-none">
                        <MarkdownRenderer
                          content={stopNote.content.slice(0, 1000)}
                          notes={notes}
                        />
                        {stopNote.content.length > 1000 && (
                          <p className="text-xs text-muted-foreground mt-2">
                            ... (truncated, {stopNote.content.length} total chars)
                          </p>
                        )}
                      </div>
                    </CardContent>
                  </Card>
                )}
              </CardContent>
            </Card>

            {/* Navigation */}
            <div className="flex items-center justify-between">
              <Button
                variant="outline"
                disabled={currentStop === 0}
                onClick={() => setCurrentStop(s => Math.max(0, s - 1))}
              >
                <ArrowLeft className="mr-2 h-4 w-4" /> Previous
              </Button>
              <Button
                disabled={currentStop >= tourStops.length - 1}
                onClick={() => setCurrentStop(s => Math.min(tourStops.length - 1, s + 1))}
              >
                {currentStop >= tourStops.length - 1 ? 'Done' : <><ArrowRight className="mr-2 h-4 w-4" /> Next</>}
              </Button>
            </div>
          </>
        )}
      </div>
    );
  }

  // Tour list view
  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-3xl font-bold tracking-tight flex items-center gap-3">
            <Route className="h-7 w-7 text-primary" />
            Guided Tours
          </h1>
          <p className="text-muted-foreground">Curated walks through knowledge graph nodes</p>
        </div>
      </div>

      {error ? (
        <Card>
          <CardContent className="py-12 text-center">
            <AlertCircle className="h-8 w-8 mx-auto mb-2 text-destructive/50" />
            <p className="text-sm text-muted-foreground">{error}</p>
          </CardContent>
        </Card>
      ) : loading ? (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
          {Array.from({ length: 3 }).map((_, i) => (
            <Card key={i}>
              <CardContent className="p-6 space-y-3">
                <Skeleton className="h-5 w-3/5" />
                <Skeleton className="h-3 w-full" />
                <Skeleton className="h-3 w-4/5" />
              </CardContent>
            </Card>
          ))}
        </div>
      ) : tours.length === 0 ? (
        <Card>
          <CardContent className="py-16 text-center text-muted-foreground">
            <Route className="h-12 w-12 mx-auto mb-3 opacity-30" />
            <p className="text-lg font-medium">No tours yet</p>
            <p className="text-sm mt-1">Create tours via the API or MCP server.</p>
          </CardContent>
        </Card>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
          {tours.map((tour: TourRow) => {
            const stopCount = stops?.filter((s: TourStopRow) => s.tour_id === tour.id).length || 0;
            return (
              <Card
                key={tour.id}
                className="cursor-pointer hover:bg-accent/50 transition-colors"
                onClick={() => { setActiveTourId(tour.id); setCurrentStop(0); }}
              >
                <CardContent className="p-6">
                  <div className="flex items-start gap-3">
                    <Compass className="h-5 w-5 text-primary shrink-0 mt-0.5" />
                    <div className="min-w-0">
                      <h3 className="font-semibold truncate">{tour.title}</h3>
                      <p className="text-sm text-muted-foreground mt-1 line-clamp-2">
                        {tour.description || 'No description'}
                      </p>
                      <div className="flex items-center gap-2 mt-3">
                        <Badge variant="secondary" className="text-xs">
                          {stopCount} stop{stopCount !== 1 ? 's' : ''}
                        </Badge>
                        <Button size="sm" variant="ghost" className="ml-auto">
                          <Play className="h-3 w-3 mr-1" /> Start
                        </Button>
                      </div>
                    </div>
                  </div>
                </CardContent>
              </Card>
            );
          })}
        </div>
      )}
    </div>
  );
}
