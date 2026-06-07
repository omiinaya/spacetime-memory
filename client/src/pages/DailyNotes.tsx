import { useState, useEffect, useMemo, useCallback } from 'react';
import { Card, CardContent } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Skeleton } from '@/components/ui/skeleton';
import { useTable } from '@/lib/useReactiveDb';
import { MarkdownRenderer } from '@/components/MarkdownRenderer';
import { callReducer } from '@/lib/spacetimedb';
import {
  ChevronLeft, ChevronRight, Save, Edit3, Eye, CalendarDays,
  Sparkles, AlertCircle,
} from 'lucide-react';

interface NoteRow {
  id: string;
  title: string;
  content: string;
  note_date: string;
  embedding_json: string;
  backlink_count: number;
  created_at: number;
  updated_at: number;
  is_active: boolean;
}

function todayDate(): string {
  const d = new Date();
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, '0');
  const day = String(d.getDate()).padStart(2, '0');
  return `${y}-${m}-${day}`;
}

function formatDate(dateStr: string): string {
  const [y, m, d] = dateStr.split('-');
  const months = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
  const days = ['Sunday', 'Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday'];
  const dt = new Date(Number(y), Number(m) - 1, Number(d));
  return `${days[dt.getDay()]}, ${months[Number(m) - 1]} ${Number(d)}, ${y}`;
}

function shiftDate(dateStr: string, delta: number): string {
  const [y, m, d] = dateStr.split('-').map(Number);
  const dt = new Date(y, m - 1, d + delta);
  const ny = dt.getFullYear();
  const nm = String(dt.getMonth() + 1).padStart(2, '0');
  const nd = String(dt.getDate()).padStart(2, '0');
  return `${ny}-${nm}-${nd}`;
}

export default function DailyNotes() {
  const { data: notes, loading, error } = useTable<NoteRow>('note');
  const [currentDate, setCurrentDate] = useState(todayDate());
  const [editing, setEditing] = useState(false);
  const [editContent, setEditContent] = useState('');
  const [saving, setSaving] = useState(false);

  const isToday = currentDate === todayDate();

  // Find note for current date
  const dailyNote = useMemo(() => {
    return notes.find((n: NoteRow) => n.note_date === currentDate && n.is_active) ?? null;
  }, [notes, currentDate]);

  // Initialize edit content when note changes
  useEffect(() => {
    if (dailyNote && editing) {
      setEditContent(dailyNote.content);
    }
  }, [dailyNote?.id]);

  const handleCreate = useCallback(async () => {
    setSaving(true);
    try {
      await callReducer('create_note', [
        'default',           // workspace_id
        '',                  // title (auto-extracted from content)
        `# Daily Notes — ${currentDate}\n\n<!-- Start writing your daily notes here -->\n\n## Tasks\n\n- [ ] \n\n## Notes\n\n`,
        currentDate,         // note_date
        '[]',                // embedding_json
      ]);
    } catch (e: any) {
      alert(`Failed to create daily note: ${e.message}`);
    } finally {
      setSaving(false);
    }
  }, [currentDate]);

  const handleSave = useCallback(async () => {
    if (!dailyNote) return;
    setSaving(true);
    try {
      await callReducer('update_note', [dailyNote.id, dailyNote.title, editContent, '']);
      setEditing(false);
    } catch (e: any) {
      alert(`Save failed: ${e.message}`);
    } finally {
      setSaving(false);
    }
  }, [dailyNote, editContent]);

  return (
    <div className="space-y-6">
      {/* Header */}
      <div>
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <CalendarDays className="h-6 w-6 text-primary" />
            <h1 className="text-3xl font-bold tracking-tight">Daily Notes</h1>
            {isToday && <Sparkles className="h-5 w-5 text-yellow-500" />}
          </div>
          <div className="flex items-center gap-2">
            <Button variant="outline" size="icon" onClick={() => setCurrentDate(shiftDate(currentDate, -1))}>
              <ChevronLeft className="h-4 w-4" />
            </Button>
            <Button
              variant={isToday ? 'default' : 'outline'}
              size="sm"
              onClick={() => setCurrentDate(todayDate())}
            >
              Today
            </Button>
            <Button variant="outline" size="icon" onClick={() => setCurrentDate(shiftDate(currentDate, 1))}>
              <ChevronRight className="h-4 w-4" />
            </Button>
          </div>
        </div>
        <p className="text-muted-foreground mt-1">{formatDate(currentDate)}</p>
      </div>

      {/* Daily note editor / viewer */}
      <Card className="min-h-[50vh]">
        <CardContent className="p-6">
          {error ? (
            <div className="flex items-center gap-3 py-6 text-destructive">
              <AlertCircle className="h-5 w-5" />
              <p className="text-sm">{error}</p>
            </div>
          ) : loading ? (
            <div className="space-y-4">
              <Skeleton className="h-6 w-64" />
              <Skeleton className="h-4 w-full" />
              <Skeleton className="h-4 w-5/6" />
              <Skeleton className="h-4 w-4/6" />
            </div>
          ) : !dailyNote ? (
            <div className="flex flex-col items-center justify-center py-16 text-center">
              <CalendarDays className="h-12 w-12 mb-4 text-muted-foreground/30" />
              <p className="text-lg font-medium text-muted-foreground">No note for this day yet</p>
              <p className="text-sm text-muted-foreground mt-1">
                {isToday
                  ? 'Start your daily notes for today.'
                  : 'This day doesn\'t have a note yet.'}
              </p>
              <Button
                className="mt-4"
                onClick={handleCreate}
                disabled={saving}
              >
                {saving ? 'Creating...' : `Create Note for ${currentDate}`}
              </Button>
            </div>
          ) : (
            <div>
              {/* Editor/viewer toolbar */}
              <div className="flex items-center justify-between mb-4 pb-3 border-b border-border">
                <div className="flex items-center gap-2">
                  <h2 className="text-lg font-semibold">
                    {dailyNote.title || formatDate(currentDate)}
                  </h2>
                  {dailyNote.backlink_count > 0 && (
                    <span className="text-xs text-muted-foreground bg-muted px-2 py-0.5 rounded-full">
                      {dailyNote.backlink_count} backlink(s)
                    </span>
                  )}
                </div>
                {editing ? (
                  <div className="flex items-center gap-2">
                    <Button variant="outline" size="sm" onClick={() => { setEditing(false); setEditContent(''); }}>
                      <Eye className="mr-2 h-4 w-4" /> View
                    </Button>
                    <Button size="sm" onClick={handleSave} disabled={saving}>
                      <Save className="mr-2 h-4 w-4" />
                      {saving ? 'Saving...' : 'Save'}
                    </Button>
                  </div>
                ) : (
                  <Button variant="outline" size="sm" onClick={() => { setEditing(true); setEditContent(dailyNote.content); }}>
                    <Edit3 className="mr-2 h-4 w-4" /> Edit
                  </Button>
                )}
              </div>

              {/* Content */}
              {editing ? (
                <textarea
                  className="w-full min-h-[40vh] bg-transparent resize-none outline-none font-mono text-sm leading-relaxed"
                  value={editContent}
                  onChange={e => setEditContent(e.target.value)}
                />
              ) : (
                <div className="prose prose-sm prose-invert max-w-none">
                  <MarkdownRenderer content={dailyNote.content} notes={notes} currentNoteId={dailyNote.id} />
                </div>
              )}
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
