import React from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { useLocation } from 'wouter';

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

interface MarkdownRendererProps {
  content: string;
  notes: Array<{ id: string; title: string }>;
  currentNoteId?: string;
}

export function MarkdownRenderer({ content, notes, currentNoteId }: MarkdownRendererProps) {
  const [, setLocation] = useLocation();

  // Replace [[wikilinks]] with custom components
  const processed = React.useMemo(() => {
    // Split on wikilinks and build the markdown with custom link syntax
    // We use a special format: [display](wikilink:target-title)
    return content.replace(wikiLinkPattern, (match) => {
      const target = targetTitleFromWikiLink(match);
      if (!target) return match;
      const display = displayNameFromWikiLink(match) || target;
      const found = notes.find(n => n.title === target && n.id !== currentNoteId);
      if (found) {
        return `[${display}](wikilink://${encodeURI(target)}?noteId=${found.id})`;
      } else {
        // Dead/absent wikilink — render as muted text
        return `[${display}](wikilink://${encodeURI(target)}?missing=1)`;
      }
    });
  }, [content, notes, currentNoteId]);

  const handleLinkClick = React.useCallback((e: React.MouseEvent, href: string) => {
    if (!href.startsWith('wikilink://')) return;
    e.preventDefault();
    const url = new URL(href);
    const noteId = url.searchParams.get('noteId');
    if (noteId) {
      setLocation(`/notes/${noteId}`);
    }
    // If missing, no-op — just prevent navigation
  }, [setLocation]);

  return (
    <div onClick={(e) => {
      const link = (e.target as HTMLElement).closest('a');
      if (link?.getAttribute('href')?.startsWith('wikilink://')) {
        handleLinkClick(e, link.getAttribute('href')!);
      }
    }}>
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        components={{
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
          // Styling for all markdown elements
          h1: ({ children }) => <h1 className="text-2xl font-bold mt-6 mb-3">{children}</h1>,
          h2: ({ children }) => <h2 className="text-xl font-bold mt-5 mb-2">{children}</h2>,
          h3: ({ children }) => <h3 className="text-lg font-semibold mt-4 mb-2">{children}</h3>,
          p: ({ children }) => <p className="my-2 leading-relaxed">{children}</p>,
          ul: ({ children }) => <ul className="list-disc pl-6 my-2 space-y-1">{children}</ul>,
          ol: ({ children }) => <ol className="list-decimal pl-6 my-2 space-y-1">{children}</ol>,
          li: ({ children }) => <li>{children}</li>,
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
