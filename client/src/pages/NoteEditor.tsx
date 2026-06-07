import { useState, useCallback, useEffect, useMemo } from 'react';
import { useRoute, useLocation } from 'wouter';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { Skeleton } from '@/components/ui/skeleton';
import {
  Save, Eye, Edit3, ArrowLeft, ExternalLink, Trash2,
  CornerDownRight, MessageSquare, Hash,
} from 'lucide-react';
import { useTable } from '@/lib/useReactiveDb';
import { MarkdownRenderer, BlockView, BlockBacklinksPanel } from '@/components/MarkdownRenderer';
import { callReducer } from '@/lib/spacetimedb';

interface NoteRow {
  id: string;
  title: string;
  content: string;
  note_date: string;
  embedding_json: string;
  backlink_count: number;
  block_ref_count: number;
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

interface NoteBlockRow {
  id: string;
  note_id: string;
  block_type: string;
  content: string;
  source: string;
  block_order: number;
  heading_level: number;
  task_state: string;
  properties_json: string;
  is_active: boolean;
  created_at: number;
}

interface BlockReferenceRow {
  id: string;
  source_note_id: string;
  source_block_id: string;
  target_block_id: string;
  target_note_id: string;
  ref_type: string;
  created_at: number;
}


export default function NoteEditor() {
  const [, params] = useRoute('/notes/:id');
  const [, setLocation] = useLocation();
  const isNew = !params?.id || params.id === 'new';
  const noteId = isNew ? null : params!.id;

  const { data: notes } = useTable<NoteRow>('note');
  const { data: allBacklinks, loading: blLoading } = useTable<NoteBacklinkRow>('note_backlink');
  const { data: noteBlocks } = useTable<NoteBlockRow>('note_block');
  const { data: blockReferences } = useTable<BlockReferenceRow>('block_reference');

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

  // Get blocks for this note
  const thisNotesBlocks = useMemo(() => {
    if (!noteId) return [];
    return (noteBlocks || [])
      .filter((b: NoteBlockRow) => b.note_id === noteId)
      .sort((a: NoteBlockRow, b: NoteBlockRow) => a.block_order - b.block_order);
  }, [noteBlocks, noteId]);

  const [title, setTitle] = useState('');
  const [content, setContent] = useState('');
  const [preview, setPreview] = useState(false);
  const [saving, setSaving] = useState(false);
  const [dirty, setDirty] = useState(false);
  const [showBlocks, setShowBlocks] = useState(false);
  const [highlightBlock, setHighlightBlock] = useState<number | null>(null);

  // Check for ?block=N query param on mount
  useEffect(() => {
    const searchParams = new URLSearchParams(window.location.search);
    const blockParam = searchParams.get('block');
    if (blockParam) {
      setHighlightBlock(parseInt(blockParam, 10));
      setShowBlocks(true);
    }
  }, []);

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
    const m = content.matchAll(/\[\[([^\[\]]+?)\]\]/g);
    for (const match of m) {
      const t = match[1].trim();
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

  // Block refs in this note's content
  const blockRefCount = useMemo(() => {
    const refs = content.match(/\(\([^()]+?\)\)/g);
    return refs?.length || 0;
  }, [content]);

  const embedCount = useMemo(() => {
    const embeds = content.match(/\{\{embed\s*\(\([^()]+?\)\)\}\}/g);
    return embeds?.length || 0;
  }, [content]);

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
          {!isNew && (
            <>
              <Button
                variant={showBlocks ? 'default' : 'outline'}
                size="sm"
                onClick={() => setShowBlocks(!showBlocks)}
                title="Toggle block view"
              >
                <Hash className="mr-2 h-4 w-4" />
                Blocks
              </Button>
            </>
          )}
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
      {showBlocks && thisNotesBlocks.length > 0 && !preview ? (
        /* Block view */
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm flex items-center gap-2">
              <Hash className="h-4 w-4" />
              Blocks ({thisNotesBlocks.length})
            </CardTitle>
          </CardHeader>
          <CardContent className="p-0">
            <BlockView
              blocks={thisNotesBlocks}
              notes={notes}
              currentNoteId={noteId || undefined}
              noteBlocks={noteBlocks}
              highlightBlock={highlightBlock}
            />
          </CardContent>
        </Card>
      ) : (
        /* Editor/Preview panels */
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
                  placeholder={
                    'Write in markdown...\n\n' +
                    '[[WikiLinks]] to link to other notes.\n' +
                    '((block-id)) to reference a specific block.\n' +
                    '{{embed ((block-id))}} to transclude a block.\n' +
                    '# Heading auto-becomes the title.\n'
                  }
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
                  <MarkdownRenderer
                    content={content}
                    notes={notes}
                    currentNoteId={noteId || undefined}
                    noteBlocks={noteBlocks}
                  />
                </div>
              )}
            </CardContent>
          </Card>
        </div>
      )}

      {/* Block ref count badge */}
      {(blockRefCount > 0 || embedCount > 0) && (
        <div className="flex items-center gap-2 text-xs text-muted-foreground">
          <MessageSquare className="h-3 w-3" />
          <span>{blockRefCount} block reference(s)</span>
          {embedCount > 0 && <>, {embedCount} embed(s)</>}
          <span className="text-[10px] text-muted-foreground/50">
            (Use ((id)) syntax to reference blocks. Hover blocks to see their IDs.)
          </span>
        </div>
      )}

      {/* Quick info: wikilinks + backlinks + block refs */}
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

      {/* Block references panel */}
      {!isNew && blockReferences && blockReferences.length > 0 && (
        <BlockBacklinksPanel
          noteId={noteId!}
          blockReferences={blockReferences}
          notes={notes}
          onNavigate={(path: string) => setLocation(path)}
        />
      )}

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
