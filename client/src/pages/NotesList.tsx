import { useMemo } from 'react';
import { useLocation } from 'wouter';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { Skeleton } from '@/components/ui/skeleton';
import { useTable } from '@/lib/useReactiveDb';
import { FileText, AlertCircle, Link } from 'lucide-react';

interface NoteRow {
  id: string;
  title: string;
  content: string;
  note_date: string;
  backlink_count: number;
  updated_at: number;
  is_active: boolean;
}

function fmt(micros: number | null): string {
  if (micros == null) return 'unknown';
  const ms = micros / 1000;
  const diff = Date.now() - ms;
  const s = Math.floor(diff / 1000);
  if (s < 60) return `${s}s ago`;
  const m = Math.floor(s / 60);
  if (m < 60) return `${m}m ago`;
  const h = Math.floor(m / 60);
  if (h < 24) return `${h}h ago`;
  return `${Math.floor(h / 24)}d ago`;
}

export default function NotesList() {
  const [, setLocation] = useLocation();
  const { data: notes, loading, error } = useTable<NoteRow>('note');

  const activeNotes = useMemo(() => notes.filter(n => n.is_active), [notes]);

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-3xl font-bold tracking-tight">Notes</h1>
          <p className="text-muted-foreground">
            {loading ? 'Loading...' : `${activeNotes.length} note(s)`}
          </p>
        </div>
        <Button onClick={() => setLocation('/notes/new')}>
          <FileText className="mr-2 h-4 w-4" /> New Note
        </Button>
      </div>

      <Card>
        <CardHeader>
          <CardTitle className="text-lg">All Notes</CardTitle>
        </CardHeader>
        <CardContent>
          {error ? (
            <div className="flex items-center gap-3 py-6 text-destructive">
              <AlertCircle className="h-5 w-5" />
              <p className="text-sm">{error}</p>
            </div>
          ) : loading ? (
            <div className="space-y-3">
              {Array.from({ length: 4 }).map((_, i) => (
                <div key={i} className="flex items-center justify-between rounded-lg border border-border p-3">
                  <div className="space-y-1 flex-1">
                    <Skeleton className="h-5 w-56" />
                    <Skeleton className="h-3 w-32 mt-1" />
                  </div>
                  <Skeleton className="h-5 w-16 ml-3" />
                </div>
              ))}
            </div>
          ) : activeNotes.length === 0 ? (
            <div className="flex flex-col items-center justify-center py-12 text-muted-foreground">
              <FileText className="h-10 w-10 mb-3 opacity-30" />
              <p className="font-medium">No notes yet</p>
              <p className="text-sm mt-1">Create your first note to get started.</p>
            </div>
          ) : (
            <div className="space-y-2">
              {activeNotes.map(note => (
                <div
                  key={note.id}
                  className="flex items-center justify-between rounded-lg border border-border p-3 hover:bg-accent/50 cursor-pointer transition-colors"
                  onClick={() => setLocation(`/notes/${note.id}`)}
                >
                  <div className="flex items-start gap-3 min-w-0 flex-1 mr-3">
                    <FileText className="mt-0.5 h-4 w-4 text-muted-foreground shrink-0" />
                    <div className="min-w-0">
                      <p className="font-medium truncate max-w-[400px]">
                        {note.title || 'Untitled'}
                      </p>
                      <p className="text-xs text-muted-foreground">
                        {note.note_date && <Badge variant="outline" className="mr-2 text-xs">{note.note_date}</Badge>}
                        {note.backlink_count > 0 && `${note.backlink_count} backlink(s)`}
                        {note.note_date && note.backlink_count > 0 && ' · '}
                        Updated {fmt(note.updated_at)}
                      </p>
                    </div>
                  </div>
                  <div className="flex items-center gap-2 shrink-0">
                    {note.backlink_count > 0 && (
                      <Badge variant="secondary" className="text-xs">
                        <Link className="h-3 w-3 mr-1" />{note.backlink_count}
                      </Badge>
                    )}
                    <Badge variant="outline" className="text-xs">
                      {note.content.length > 100 ? `${note.content.length}B` : `${note.content.split('\n').length}L`}
                    </Badge>
                  </div>
                </div>
              ))}
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
