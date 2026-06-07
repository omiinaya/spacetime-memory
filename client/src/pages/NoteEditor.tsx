import { useState, useCallback, useEffect, useMemo } from 'react';
import { useRoute, useLocation } from 'wouter';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { Skeleton } from '@/components/ui/skeleton';
import {
  Save, Eye, Edit3, ArrowLeft, ExternalLink, Trash2,
  CornerDownRight,
} from 'lucide-react';
import { useTable } from '@/lib/useReactiveDb';
import { MarkdownRenderer, wikiLinkPattern, targetTitleFromWikiLink } from '@/components/MarkdownRenderer';
import { callReducer } from '@/lib/spacetimedb';

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

interface NoteBacklinkRow {
  id: string;
  source_note_id: string;
  target_note_id: string;
  display_text: string;
  created_at: number;
}


export default function NoteEditor() {
  const [, params] = useRoute('/notes/:id');
  const [, setLocation] = useLocation();
  const isNew = !params?.id || params.id === 'new';
  const noteId = isNew ? null : params!.id;

  const { data: notes } = useTable<NoteRow>('note');
  const { data: allBacklinks, loading: blLoading } = useTable<NoteBacklinkRow>('note_backlink');

  const note = useMemo(() => {
    if (isNew) return null;
    return notes.find((n: NoteRow) => n.id === noteId) ?? null;
  }, [notes, noteId, isNew]);

  const backlinks = useMemo(() => {
    if (!noteId) return [];
    return allBacklinks
      .filter((bl: NoteBacklinkRow) => bl.target_note_id === noteId)
      .map(bl => {
        const src = notes.find((n: NoteRow) => n.id === bl.source_note_id);
        return { ...bl, sourceTitle: src?.title || '(deleted)' };
      });
  }, [allBacklinks, noteId, notes]);

  const [title, setTitle] = useState('');
  const [content, setContent] = useState('');
  const [preview, setPreview] = useState(false);
  const [saving, setSaving] = useState(false);
  const [dirty, setDirty] = useState(false);

  // Initialize state from note or new
  useEffect(() => {
    if (isNew) {
      setTitle('');
      setContent('');
      setDirty(false);
    } else if (note) {
      setTitle(note.title || '');
      setContent(note.content || '');
      setDirty(false);
    }
  }, [note?.id, isNew]);

  const handleSave = useCallback(async () => {
    setSaving(true);
    try {
      if (isNew) {
        await callReducer('create_note', ['default', title, content, '', '[]']);
        setLocation('/notes');
      } else if (noteId) {
        await callReducer('update_note', [noteId, title, content, '']);
        setDirty(false);
      }
    } catch (e: any) {
      alert(`Save failed: ${e.message}`);
    } finally {
      setSaving(false);
    }
  }, [isNew, noteId, title, content, setLocation]);

  // Parse wikilinks in content for link targets
  const wikiTargets = useMemo(() => {
    const targets: string[] = [];
    const m = content.matchAll(wikiLinkPattern);
    for (const match of m) {
      const t = targetTitleFromWikiLink(match[0]);
      if (t) targets.push(t);
    }
    return targets;
  }, [content]);

  // Title from content heuristics
  useEffect(() => {
    if (title || !content) return;
    for (const line of content.split('\n')) {
      const t = line.trim();
      if (t.startsWith('# ')) {
        setTitle(t.slice(2).trim());
        break;
      }
    }
  }, [content, title]);

  const savingDisplay = saving ? 'Saving...' : dirty ? 'Unsaved changes' : 'Saved';

  // Linked notes info
  const linkedNotes = useMemo(() => {
    if (wikiTargets.length === 0) return [];
    return wikiTargets.map(t => {
      const found = notes.find((n: NoteRow) => n.title === t && n.id !== noteId);
      return { title: t, exists: !!found, noteId: found?.id };
    });
  }, [wikiTargets, notes, noteId]);

  return (
    <div className="space-y-4">
      {/* Header */}
      <div className="flex items-center justify-between gap-4">
        <div className="flex items-center gap-2 min-w-0">
          <Button variant="ghost" size="icon" onClick={() => setLocation('/notes')}>
            <ArrowLeft className="h-4 w-4" />
          </Button>
          <div className="min-w-0">
            <h1 className="text-xl font-bold tracking-tight truncate max-w-[500px]">
              {isNew ? 'New Note' : (note?.title || 'Untitled')}
            </h1>
            <p className="text-xs text-muted-foreground">{savingDisplay}</p>
          </div>
        </div>
        <div className="flex items-center gap-2 shrink-0">
          <Button
            variant="outline"
            size="sm"
            onClick={() => setPreview(!preview)}
          >
            {preview ? <Edit3 className="mr-2 h-4 w-4" /> : <Eye className="mr-2 h-4 w-4" />}
            {preview ? 'Edit' : 'Preview'}
          </Button>
          <Button size="sm" onClick={handleSave} disabled={saving || (!dirty && !isNew)}>
            <Save className="mr-2 h-4 w-4" />
            {isNew ? 'Create' : 'Save'}
          </Button>
        </div>
      </div>

      {/* Content area */}
      <div className="grid grid-cols-1 gap-4" style={{ gridTemplateColumns: preview ? '1fr' : '1fr 1fr' }}>
        {/* Editor panel */}
        {!preview && (
          <Card className="min-h-[60vh]">
            <CardContent className="p-4">
              <input
                type="text"
                placeholder="Note title (or use # Heading in content)"
                className="w-full bg-transparent text-lg font-semibold border-b border-border pb-2 mb-4 outline-none placeholder:text-muted-foreground/50"
                value={title}
                onChange={e => { setTitle(e.target.value); setDirty(true); }}
              />
              <textarea
                className="w-full min-h-[50vh] bg-transparent resize-none outline-none font-mono text-sm leading-relaxed"
                placeholder="Write in markdown...&#10;&#10;Use [[WikiLinks]] to link to other notes.&#10;# Heading auto-becomes the title.&#10;"
                value={content}
                onChange={e => { setContent(e.target.value); setDirty(true); }}
              />
            </CardContent>
          </Card>
        )}

        {/* Preview panel (or full-screen in preview mode) */}
        <Card className="min-h-[60vh]">
          <CardContent className="p-4">
            {!content && !preview ? (
              <div className="flex flex-col items-center justify-center h-[50vh] text-muted-foreground">
                <Edit3 className="h-8 w-8 mb-2 opacity-30" />
                <p className="text-sm">Start typing markdown on the left</p>
              </div>
            ) : (
              <div className="prose prose-sm prose-invert max-w-none">
                {title && <h1 className="text-2xl font-bold mb-4">{title}</h1>}
                <MarkdownRenderer content={content} notes={notes} currentNoteId={noteId || undefined} />
              </div>
            )}
          </CardContent>
        </Card>
      </div>

      {/* Quick info: wikilinks + backlinks */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        {/* Outgoing wikilinks */}
        {wikiTargets.length > 0 && (
          <Card>
            <CardHeader className="pb-2">
              <CardTitle className="text-sm flex items-center gap-2">
                <ExternalLink className="h-4 w-4" />
                Linked Notes ({wikiTargets.length})
              </CardTitle>
            </CardHeader>
            <CardContent>
              <div className="flex flex-wrap gap-2">
                {linkedNotes.map(ln => (
                  <Badge
                    key={ln.title}
                    variant={ln.exists ? 'default' : 'secondary'}
                    className="cursor-pointer"
                    onClick={() => ln.exists && ln.noteId && setLocation(`/notes/${ln.noteId}`)}
                  >
                    {ln.title}
                    {!ln.exists && ' (new)'}
                  </Badge>
                ))}
              </div>
            </CardContent>
          </Card>
        )}

        {/* Backlinks panel */}
        {!isNew && (
          <Card>
            <CardHeader className="pb-2">
              <CardTitle className="text-sm flex items-center gap-2">
                <CornerDownRight className="h-4 w-4" />
                Backlinks ({backlinks.length})
              </CardTitle>
            </CardHeader>
            <CardContent>
              {blLoading ? (
                <div className="space-y-2">
                  <Skeleton className="h-4 w-48" />
                  <Skeleton className="h-4 w-32" />
                </div>
              ) : backlinks.length === 0 ? (
                <p className="text-xs text-muted-foreground">No notes link to this note yet.</p>
              ) : (
                <div className="space-y-2">
                  {backlinks.map(bl => (
                    <div
                      key={bl.id}
                      className="flex items-center gap-2 text-sm cursor-pointer hover:text-accent-foreground transition-colors"
                      onClick={() => setLocation(`/notes/${bl.source_note_id}`)}
                    >
                      <CornerDownRight className="h-3 w-3 shrink-0 text-muted-foreground" />
                      <span className="font-medium truncate">{bl.sourceTitle}</span>
                      <span className="text-xs text-muted-foreground">via [{bl.display_text}]</span>
                    </div>
                  ))}
                </div>
              )}
            </CardContent>
          </Card>
        )}
      </div>

      {/* Delete button for existing notes */}
      {!isNew && (
        <div className="flex justify-end">
          <Button
            variant="destructive"
            size="sm"
            onClick={async () => {
              if (!confirm('Delete this note?')) return;
              try {
                await callReducer('delete_note', [noteId!]);
                setLocation('/notes');
              } catch (e: any) {
                alert(`Delete failed: ${e.message}`);
              }
            }}
          >
            <Trash2 className="mr-2 h-4 w-4" /> Delete Note
          </Button>
        </div>
      )}
    </div>
  );
}
