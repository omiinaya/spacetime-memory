import React from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { useLocation } from 'wouter';
import { Card, CardContent } from '@/components/ui/card';
import { CornerDownRight, MessageSquare, ExternalLink } from 'lucide-react';

// Wikilink pattern: [[Title]] or [[Title|Display]]
export const wikiLinkPattern = /\[\[([^\[\]]+?)\]\]/g;

export function targetTitleFromWikiLink(match: string): string | null {
  const inner = match.slice(2, -2);
  const pipeIdx = inner.indexOf('|');
  return pipeIdx >= 0 ? inner.slice(0, pipeIdx).trim() : inner.trim();
}

export function displayNameFromWikiLink(match: string): string {
  const inner = match.slice(2, -2);
  const pipeIdx = inner.indexOf('|');
  if (pipeIdx >= 0) return inner.slice(pipeIdx + 1).trim();
  return inner.trim();
}

// Block reference patterns
const blockRefPattern = /\(\(([^()]+?)\)\)/g;
const embedPattern = /\{\{embed\s*\(\(([^()]+?)\)\)\}\}/g;

// DB snake_case types (matches what useTable returns)
export interface NoteBlockRowDb {
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

export interface BlockReferenceRowDb {
  id: string;
  source_note_id: string;
  source_block_id: string;
  target_block_id: string;
  target_note_id: string;
  ref_type: string;
  created_at: number;
}

interface MarkdownRendererProps {
  content: string;
  notes: Array<{ id: string; title: string }>;
  currentNoteId?: string;
  noteBlocks?: NoteBlockRowDb[];
}

/** Find a block by its full ID from the available blocks array */
function findBlockById(blocks: NoteBlockRowDb[] | undefined, blockId: string): NoteBlockRowDb | null {
  if (!blocks) return null;
  const found = blocks.find(b => b.id === blockId || b.id.endsWith(':' + blockId));
  if (found) return found;
  const colonIdx = blockId.indexOf(':');
  const orderHex = colonIdx >= 0 ? blockId.slice(colonIdx + 1) : blockId;
  const order = parseInt(orderHex, 16);
  if (!isNaN(order)) {
    return blocks.find(b => b.block_order === order) ?? null;
  }
  return null;
}

/** Find note title by note ID */
function findNoteTitle(notes: Array<{ id: string; title: string }>, noteId: string): string {
  const n = notes.find(n => n.id === noteId);
  return n?.title || '(deleted)';
}

/** EmbedBlock: fetches a block's content from a separate note to display inline */
function EmbedBlock({ blockId, noteBlocks, notes, currentNoteId }: {
  blockId: string;
  noteBlocks?: NoteBlockRowDb[];
  notes: Array<{ id: string; title: string }>;
  currentNoteId?: string;
}) {
  const block = findBlockById(noteBlocks, blockId);
  if (!block) {
    return (
      <span className="text-muted-foreground/60 border border-dashed border-muted-foreground/30 px-2 py-1 rounded text-xs italic">
        Missing block: {blockId}
      </span>
    );
  }

  return (
    <Card className="border-l-2 border-l-primary/40 my-2 bg-muted/30">
      <CardContent className="p-3">
        <div className="text-xs text-muted-foreground mb-1 flex items-center gap-2">
          <MessageSquare className="h-3 w-3" />
          <span>Embed from {findNoteTitle(notes, block.note_id)}</span>
        </div>
        <div className="prose prose-sm prose-invert max-w-none text-sm">
          <MarkdownRenderer
            content={block.content}
            notes={notes}
            currentNoteId={currentNoteId}
            noteBlocks={noteBlocks}
          />
        </div>
      </CardContent>
    </Card>
  );
}

/** BlockRef: renders a ((block-id)) reference as a clickable link */
function BlockRef({ blockId, noteBlocks, notes, setLocation }: {
  blockId: string;
  noteBlocks?: NoteBlockRowDb[];
  notes: Array<{ id: string; title: string }>;
  setLocation: (path: string) => void;
}) {
  const block = findBlockById(noteBlocks, blockId);
  if (!block) {
    return (
      <span className="text-muted-foreground/60 border-b border-dotted border-muted-foreground/30 cursor-default text-sm">
        (({blockId}))
      </span>
    );
  }

  const noteTitle = findNoteTitle(notes, block.note_id);
  const preview = block.content.slice(0, 80);

  return (
    <span
      className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded bg-accent/40 border border-border text-xs cursor-pointer hover:bg-accent transition-colors"
      onClick={() => {
        if (block.note_id) {
          setLocation(`/notes/${block.note_id}?block=${block.block_order}`);
        }
      }}
      title={`${noteTitle} / ${preview}${block.content.length > 80 ? '...' : ''}`}
    >
      <CornerDownRight className="h-3 w-3 text-muted-foreground" />
      {preview || '(empty block)'}
    </span>
  );
}

// ---------------------------------------------------------------------------
// Helper: replace special tokens in text with inline components
// ---------------------------------------------------------------------------

function renderInlineBlocks(
  text: string,
  noteBlocks: NoteBlockRowDb[] | undefined,
  notes: Array<{ id: string; title: string }>,
  currentNoteId: string | undefined,
  setLocation: (path: string) => void,
): React.ReactNode[] {
  const parts = text.split(/(%EMBED:[^%]+%|%BLOCKREF:[^%]+%)/g);
  const elements: React.ReactNode[] = [];

  for (let idx = 0; idx < parts.length; idx++) {
    const part = parts[idx];
    if (part.startsWith('%EMBED:')) {
      const blockId = decodeURIComponent(part.slice(7, -1));
      elements.push(
        <EmbedBlock
          key={`embed-${idx}`}
          blockId={blockId}
          noteBlocks={noteBlocks}
          notes={notes}
          currentNoteId={currentNoteId}
        />
      );
    } else if (part.startsWith('%BLOCKREF:')) {
      const blockId = decodeURIComponent(part.slice(10, -1));
      elements.push(
        <BlockRef
          key={`ref-${idx}`}
          blockId={blockId}
          noteBlocks={noteBlocks}
          notes={notes}
          setLocation={setLocation}
        />
      );
    } else {
      elements.push(part);
    }
  }
  return elements;
}

/** Extract text content from React children recursively */
function extractTextContent(children: React.ReactNode): string {
  if (typeof children === 'string') return children;
  if (Array.isArray(children)) return children.map(c => extractTextContent(c)).join('');
  if (children && typeof children === 'object' && 'props' in (children as any)) {
    return extractTextContent((children as any).props.children);
  }
  return '';
}

// ---------------------------------------------------------------------------
// Main MarkdownRenderer
// ---------------------------------------------------------------------------

export function MarkdownRenderer({
  content,
  notes,
  currentNoteId,
  noteBlocks,
}: MarkdownRendererProps) {
  const [, setLocation] = useLocation();

  const processed = React.useMemo(() => {
    let result = content;

    // 1. Replace {{embed ((block-id))}} with a custom marker
    result = result.replace(embedPattern, (_match, blockId: string) => {
      const trimmed = blockId.trim();
      return `%EMBED:${encodeURIComponent(trimmed)}%`;
    });

    // 2. Replace ((block-id)) with a custom marker (only non-embed refs)
    result = result.replace(blockRefPattern, (_match, blockId: string) => {
      const trimmed = blockId.trim();
      return `%BLOCKREF:${encodeURIComponent(trimmed)}%`;
    });

    // 3. Replace [[wikilinks]] with custom link syntax
    result = result.replace(wikiLinkPattern, (match) => {
      const target = targetTitleFromWikiLink(match);
      if (!target) return match;
      const display = displayNameFromWikiLink(match) || target;
      const found = notes.find(n => n.title === target && n.id !== currentNoteId);
      if (found) {
        return `[${display}](wikilink://${encodeURI(target)}?noteId=${found.id})`;
      } else {
        return `[${display}](wikilink://${encodeURI(target)}?missing=1)`;
      }
    });

    return result;
  }, [content, notes, currentNoteId]);

  const handleLinkClick = (e: React.MouseEvent, href: string) => {
    if (!href.startsWith('wikilink://')) return;
    e.preventDefault();
    const url = new URL(href);
    const noteId = url.searchParams.get('noteId');
    if (noteId) {
      setLocation(`/notes/${noteId}`);
    }
  };

  return (
    <div
      onClick={(e) => {
        const link = (e.target as HTMLElement).closest('a');
        if (link?.getAttribute('href')?.startsWith('wikilink://')) {
          handleLinkClick(e, link.getAttribute('href')!);
        }
      }}
    >
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        components={{
          p: ({ children }) => {
            const text = extractTextContent(children);
            if (text.includes('%EMBED:') || text.includes('%BLOCKREF:')) {
              return <p className="my-2 leading-relaxed">{renderInlineBlocks(text, noteBlocks, notes, currentNoteId, setLocation)}</p>;
            }
            return <p className="my-2 leading-relaxed">{children}</p>;
          },
          li: ({ children, ...props }) => {
            const text = extractTextContent(children);
            if (text.includes('%EMBED:') || text.includes('%BLOCKREF:')) {
              return <li {...props}>{renderInlineBlocks(text, noteBlocks, notes, currentNoteId, setLocation)}</li>;
            }
            return <li {...props}>{children}</li>;
          },
          a: ({ href, children, ...props }) => {
            if (href?.startsWith('wikilink://')) {
              const url = new URL(href);
              const missing = url.searchParams.has('missing');
              if (missing) {
                return (
                  <span className="text-muted-foreground/60 border-b border-dotted border-muted-foreground/30 cursor-default">
                    [[{children}]]
                  </span>
                );
              }
              return (
                <a
                  href={href}
                  className="text-primary underline decoration-primary/30 hover:decoration-primary cursor-pointer"
                  onClick={(e) => handleLinkClick(e, href!)}
                >
                  {children}
                </a>
              );
            }
            return <a href={href} {...props}>{children}</a>;
          },
          h1: ({ children }) => <h1 className="text-2xl font-bold mt-6 mb-3">{children}</h1>,
          h2: ({ children }) => <h2 className="text-xl font-bold mt-5 mb-2">{children}</h2>,
          h3: ({ children }) => <h3 className="text-lg font-semibold mt-4 mb-2">{children}</h3>,
          ul: ({ children }) => <ul className="list-disc pl-6 my-2 space-y-1">{children}</ul>,
          ol: ({ children }) => <ol className="list-decimal pl-6 my-2 space-y-1">{children}</ol>,
          code: ({ className, children, ...props }) => {
            const isInline = !className;
            if (isInline) {
              return <code className="bg-muted px-1.5 py-0.5 rounded text-sm font-mono">{children}</code>;
            }
            return (
              <pre className="bg-muted p-4 rounded-lg overflow-x-auto my-3">
                <code className="text-sm font-mono" {...props}>{children}</code>
              </pre>
            );
          },
          blockquote: ({ children }) => (
            <blockquote className="border-l-4 border-primary/30 pl-4 my-3 italic text-muted-foreground">
              {children}
            </blockquote>
          ),
          table: ({ children }) => (
            <div className="overflow-x-auto my-3">
              <table className="min-w-full border-collapse border border-border">{children}</table>
            </div>
          ),
          th: ({ children }) => <th className="border border-border px-3 py-2 bg-muted font-semibold text-sm">{children}</th>,
          td: ({ children }) => <td className="border border-border px-3 py-2 text-sm">{children}</td>,
          hr: () => <hr className="my-6 border-border" />,
          input: (props) => <input {...props} className="mr-2" />,
        }}
      >
        {processed}
      </ReactMarkdown>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Block view component
// ---------------------------------------------------------------------------

interface BlockViewProps {
  blocks: NoteBlockRowDb[];
  notes?: Array<{ id: string; title: string }>;
  currentNoteId?: string;
  noteBlocks?: NoteBlockRowDb[];
  onBlockClick?: (blockOrder: number) => void;
  highlightBlock?: number | null;
}

/** Renders note content as individual blocks with IDs visible on hover */
export function BlockView({
  blocks,
  highlightBlock,
}: BlockViewProps) {
  if (!blocks || blocks.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center py-12 text-muted-foreground">
        <MessageSquare className="h-8 w-8 mb-2 opacity-30" />
        <p className="text-sm">No blocks yet</p>
      </div>
    );
  }

  return (
    <div className="space-y-0">
      {blocks.map((block) => {
        const isHighlighted = highlightBlock != null && block.block_order === highlightBlock;
        return (
          <div
            key={block.id}
            className={`group relative border-b border-border/40 last:border-b-0 py-1 transition-colors ${
              isHighlighted ? 'bg-accent/30 border-l-2 border-l-primary' : 'hover:bg-accent/10'
            }`}
          >
            {/* Block ID badge on hover */}
            <div className="absolute -left-1 top-0 opacity-0 group-hover:opacity-100 transition-opacity">
              <span
                className="text-[10px] font-mono text-muted-foreground/40 bg-background px-1 rounded cursor-pointer hover:text-muted-foreground/80"
                title="Block ID for ((block-id)) references"
                onClick={(e) => {
                  e.stopPropagation();
                  const shortId = block.id.split(':').pop() || block.id;
                  navigator.clipboard?.writeText(`((${shortId}))`);
                }}
              >
                {block.id.split(':').pop() || block.id}
              </span>
            </div>

            {/* Block content */}
            <div className="pl-6 pr-16">
              {block.task_state !== 'none' && (
                <span className={`inline-block text-xs mr-2 ${
                  block.task_state === 'done' ? 'text-green-500' : 'text-yellow-500'
                }`}>
                  {block.task_state === 'todo' ? '☐' : block.task_state === 'done' ? '☑' : `[${block.task_state}]`}
                </span>
              )}
              {block.block_type === 'heading' && (
                <span className="text-[10px] text-muted-foreground/50 mr-1 font-mono">
                  H{block.heading_level}
                </span>
              )}
              <span className="text-sm">
                {block.content || <span className="text-muted-foreground/40 italic">(empty)</span>}
              </span>
            </div>

            {/* Copy block ref button */}
            <div className="absolute right-2 top-1 opacity-0 group-hover:opacity-100 transition-opacity">
              <button
                className="h-5 text-[10px] px-1 rounded hover:bg-accent text-muted-foreground hover:text-foreground"
                onClick={(e) => {
                  e.stopPropagation();
                  const shortId = block.id.split(':').pop() || block.id;
                  navigator.clipboard?.writeText(`((${shortId}))`);
                }}
              >
                Copy Ref
              </button>
            </div>
          </div>
        );
      })}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Block backlinks panel
// ---------------------------------------------------------------------------

interface BlockBacklinksPanelProps {
  noteId: string;
  blockReferences: BlockReferenceRowDb[];
  notes?: Array<{ id: string; title: string }>;
  onNavigate?: (path: string) => void;
}

/** Shows which blocks reference blocks in the current note */
export function BlockBacklinksPanel({
  noteId,
  blockReferences,
  notes = [],
  onNavigate,
}: BlockBacklinksPanelProps) {
  if (!blockReferences || blockReferences.length === 0) {
    return null;
  }

  const refsToThisNote = blockReferences.filter(
    br => br.target_note_id === noteId
  );

  if (refsToThisNote.length === 0) {
    return (
      <Card>
        <CardContent className="p-4">
          <div className="flex items-center gap-2 text-xs text-muted-foreground">
            <CornerDownRight className="h-3 w-3" />
            No block references to this note
          </div>
        </CardContent>
      </Card>
    );
  }

  const grouped = new Map<string, BlockReferenceRowDb[]>();
  for (const ref of refsToThisNote) {
    if (!grouped.has(ref.source_note_id)) {
      grouped.set(ref.source_note_id, []);
    }
    grouped.get(ref.source_note_id)!.push(ref);
  }

  return (
    <Card>
      <CardContent className="p-4">
        <h4 className="text-xs font-semibold text-muted-foreground mb-2 flex items-center gap-1.5">
          <CornerDownRight className="h-3 w-3" />
          Block References ({refsToThisNote.length})
        </h4>
        <div className="space-y-2">
          {Array.from(grouped.entries()).map(([sourceNoteId, refs]) => {
            const noteTitle = findNoteTitle(notes, sourceNoteId);
            return (
              <div key={sourceNoteId}>
                <div
                  className="flex items-center gap-1.5 text-xs font-medium cursor-pointer hover:text-primary transition-colors"
                  onClick={() => onNavigate?.(`/notes/${sourceNoteId}`)}
                >
                  <ExternalLink className="h-3 w-3" />
                  {noteTitle}
                </div>
                <div className="ml-4 mt-0.5 space-y-0.5">
                  {refs.map(ref => (
                    <div
                      key={ref.id}
                      className="text-[11px] text-muted-foreground flex items-start gap-1.5"
                    >
                      <span className="shrink-0 mt-0.5">
                        {ref.ref_type === 'embed' ? '⊞' : '↳'}
                      </span>
                      <span>
                        Block {ref.target_block_id}
                        {ref.ref_type === 'embed' && ' (embedded)'}
                      </span>
                    </div>
                  ))}
                </div>
              </div>
            );
          })}
        </div>
      </CardContent>
    </Card>
  );
}
