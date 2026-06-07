import { useState, useMemo } from 'react';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Skeleton } from '@/components/ui/skeleton';
import { useTable } from '@/lib/useReactiveDb';
import { callReducer, formatMemoryTimestamp } from '@/lib/spacetimedb';
import {
  FileText,
  AlertCircle,
  Plus,
  Trash2,
  Search,
  X,
  Clock,
  RefreshCw,
  Link,
  BookOpen,
  ExternalLink,
  File,
  Image,
  Video,
  Code,
  Globe,
} from 'lucide-react';

// ─────────────────────────────────────────────────
// Types matching auto-generated SpacetimeDB bindings (camelCase)
// ─────────────────────────────────────────────────
interface DocumentRow {
  id: string;
  workspaceId: string;
  title: string;
  content: string;
  contentType: string;
  filePath: string;
  sourceUrl: string;
  metadataJson: string;
  chunkCount: number;
  createdAt: number;
  updatedAt: number;
}

// ─────────────────────────────────────────────────
// Helpers
// ─────────────────────────────────────────────────
function contentTypeIcon(type: string) {
  switch (type?.toLowerCase()) {
    case 'pdf':
      return <BookOpen className="h-4 w-4 text-red-500" />;
    case 'image':
      return <Image className="h-4 w-4 text-purple-500" />;
    case 'video':
      return <Video className="h-4 w-4 text-blue-500" />;
    case 'code':
      return <Code className="h-4 w-4 text-green-500" />;
    case 'url':
      return <Globe className="h-4 w-4 text-cyan-500" />;
    case 'text':
      return <FileText className="h-4 w-4 text-amber-500" />;
    default:
      return <File className="h-4 w-4 text-muted-foreground" />;
  }
}

function contentTypeColor(type: string): string {
  switch (type?.toLowerCase()) {
    case 'pdf':
      return 'bg-red-100 text-red-700 dark:bg-red-900/30 dark:text-red-300';
    case 'image':
      return 'bg-purple-100 text-purple-700 dark:bg-purple-900/30 dark:text-purple-300';
    case 'video':
      return 'bg-blue-100 text-blue-700 dark:bg-blue-900/30 dark:text-blue-300';
    case 'code':
      return 'bg-green-100 text-green-700 dark:bg-green-900/30 dark:text-green-300';
    case 'url':
      return 'bg-cyan-100 text-cyan-700 dark:bg-cyan-900/30 dark:text-cyan-300';
    default:
      return 'bg-gray-100 text-gray-700 dark:bg-gray-800/50 dark:text-gray-300';
  }
}

function truncateContent(content: string, max = 200): string {
  if (!content) return '';
  return content.length > max ? content.slice(0, max) + '…' : content;
}

// ─────────────────────────────────────────────────
// Loading skeleton
// ─────────────────────────────────────────────────
function LoadingSkeleton() {
  return (
    <div className="space-y-3">
      {Array.from({ length: 5 }).map((_, i) => (
        <div key={i} className="flex items-start gap-3 rounded-lg border border-border p-3">
          <Skeleton className="h-8 w-8 rounded mt-0.5 shrink-0" />
          <div className="space-y-1 flex-1 min-w-0">
            <Skeleton className="h-5 w-56" />
            <Skeleton className="h-3 w-32" />
            <Skeleton className="h-3 w-48 mt-1" />
          </div>
          <Skeleton className="h-6 w-16 rounded-full shrink-0" />
        </div>
      ))}
    </div>
  );
}

// ─────────────────────────────────────────────────
// Main component
// ─────────────────────────────────────────────────
export default function Documents() {
  const { data: docs, loading, error } = useTable<DocumentRow>('document');

  // Local state
  const [searchQuery, setSearchQuery] = useState('');
  const [selectedDocId, setSelectedDocId] = useState<string | null>(null);
  const [showCreateForm, setShowCreateForm] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);
  const [filterType, setFilterType] = useState<string>('');

  // Create form state
  const [newTitle, setNewTitle] = useState('');
  const [newContent, setNewContent] = useState('');
  const [newContentType, setNewContentType] = useState('text');
  const [newSourceUrl, setNewSourceUrl] = useState('');
  const [newWorkspaceId, setNewWorkspaceId] = useState('default');

  // Filter + sort (recent first)
  const filteredDocs = useMemo(() => {
    const q = searchQuery.toLowerCase().trim();
    let list = docs;
    if (q) {
      list = list.filter(
        (d) =>
          d.title?.toLowerCase().includes(q) ||
          d.content?.toLowerCase().includes(q) ||
          d.id?.toLowerCase().includes(q) ||
          d.workspaceId?.toLowerCase().includes(q) ||
          d.sourceUrl?.toLowerCase().includes(q),
      );
    }
    if (filterType) {
      list = list.filter((d) => d.contentType === filterType);
    }
    return [...list].sort((a, b) => (b.createdAt ?? 0) - (a.createdAt ?? 0));
  }, [docs, searchQuery, filterType]);

  const selectedDoc = useMemo(
    () => (selectedDocId ? filteredDocs.find((d) => d.id === selectedDocId) ?? null : null),
    [selectedDocId, filteredDocs],
  );

  // Unique content types for filter
  const availableTypes = useMemo(() => {
    const types = new Set<string>();
    for (const d of docs) {
      if (d.contentType) types.add(d.contentType);
    }
    return Array.from(types).sort();
  }, [docs]);

  const totalChunks = useMemo(
    () => filteredDocs.reduce((sum, d) => sum + (d.chunkCount ?? 0), 0),
    [filteredDocs],
  );

  const resetCreateForm = () => {
    setNewTitle('');
    setNewContent('');
    setNewContentType('text');
    setNewSourceUrl('');
    setNewWorkspaceId('default');
    setShowCreateForm(false);
    setActionError(null);
  };

  // Create document
  const handleCreate = async () => {
    const title = newTitle.trim();
    if (!title) {
      setActionError('Document title is required');
      return;
    }
    setSubmitting(true);
    setActionError(null);
    try {
      await callReducer('create_document', [
        newWorkspaceId,
        title,
        newContent,
        newContentType,
        '',   // file_path
        newSourceUrl,
        '{}', // metadata_json
      ]);
      resetCreateForm();
    } catch (e: any) {
      setActionError(e.message || 'Failed to create document');
    } finally {
      setSubmitting(false);
    }
  };

  // Delete document
  const handleDelete = async (id: string, title: string) => {
    if (!confirm(`Delete document "${title || id}"? This cannot be undone.`)) return;
    setActionError(null);
    try {
      await callReducer('delete_document', [id]);
      if (selectedDocId === id) setSelectedDocId(null);
    } catch (e: any) {
      setActionError(e.message || 'Failed to delete document');
    }
  };

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-3xl font-bold tracking-tight">Documents</h1>
          <p className="text-muted-foreground">
            {loading
              ? 'Loading...'
              : error
                ? 'Connection error'
                : `${filteredDocs.length} document(s) · ${totalChunks} chunk(s)`}
          </p>
        </div>
        <Button onClick={() => setShowCreateForm(true)}>
          <Plus className="mr-2 h-4 w-4" /> Create Document
        </Button>
      </div>

      {/* Action error */}
      {actionError && (
        <Card className="border-destructive/50">
          <CardContent className="flex items-center gap-3 py-3 text-sm text-destructive">
            <AlertCircle className="h-4 w-4 shrink-0" />
            <span className="flex-1">{actionError}</span>
            <Button variant="ghost" size="sm" onClick={() => setActionError(null)}>
              <X className="h-3 w-3" />
            </Button>
          </CardContent>
        </Card>
      )}

      {/* Search + type filter bar */}
      <div className="flex flex-col sm:flex-row gap-3">
        <div className="relative flex-1">
          <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
          <Input
            placeholder="Search documents by title, content, or URL..."
            className="pl-9"
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
          />
          {searchQuery && (
            <button
              className="absolute right-3 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground"
              onClick={() => setSearchQuery('')}
            >
              <X className="h-4 w-4" />
            </button>
          )}
        </div>
        {availableTypes.length > 0 && (
          <div className="flex gap-1 flex-wrap shrink-0">
            <Button
              variant={filterType === '' ? 'default' : 'outline'}
              size="sm"
              onClick={() => setFilterType('')}
            >
              All
            </Button>
            {availableTypes.map((type) => (
              <Button
                key={type}
                variant={filterType === type ? 'default' : 'outline'}
                size="sm"
                onClick={() => setFilterType(filterType === type ? '' : type)}
                className="flex items-center gap-1"
              >
                {contentTypeIcon(type)}
                {type.charAt(0).toUpperCase() + type.slice(1)}
              </Button>
            ))}
          </div>
        )}
      </div>

      {/* Create form */}
      {showCreateForm && (
        <Card className="border-primary/50">
          <CardHeader className="pb-3">
            <CardTitle className="text-lg flex items-center gap-2">
              <Plus className="h-4 w-4" />
              New Document
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="space-y-2">
              <label className="text-sm font-medium">Title *</label>
              <Input
                placeholder="e.g. Architecture Overview, Meeting Notes..."
                value={newTitle}
                onChange={(e) => setNewTitle(e.target.value)}
              />
            </div>
            <div className="space-y-2">
              <label className="text-sm font-medium">Document Type</label>
              <div className="flex gap-2 flex-wrap">
                {['text', 'pdf', 'image', 'video', 'code', 'url'].map((type) => (
                  <Button
                    key={type}
                    variant={newContentType === type ? 'default' : 'outline'}
                    size="sm"
                    onClick={() => setNewContentType(type)}
                    className="flex items-center gap-1"
                  >
                    {contentTypeIcon(type)}
                    {type.charAt(0).toUpperCase() + type.slice(1)}
                  </Button>
                ))}
              </div>
            </div>
            <div className="space-y-2">
              <label className="text-sm font-medium">Content</label>
              <textarea
                className="w-full min-h-[120px] rounded-md border border-input bg-background px-3 py-2 text-sm resize-y font-mono"
                placeholder="Paste or type document content here..."
                value={newContent}
                onChange={(e) => setNewContent(e.target.value)}
              />
            </div>
            <div className="space-y-2">
              <label className="text-sm font-medium">Source URL</label>
              <Input
                placeholder="https://example.com/document (optional)"
                value={newSourceUrl}
                onChange={(e) => setNewSourceUrl(e.target.value)}
              />
            </div>
            <div className="space-y-2">
              <label className="text-sm font-medium">Workspace ID</label>
              <Input
                placeholder="default"
                value={newWorkspaceId}
                onChange={(e) => setNewWorkspaceId(e.target.value)}
              />
            </div>
            <div className="flex items-center gap-2 pt-2">
              <Button onClick={handleCreate} disabled={submitting || !newTitle.trim()}>
                {submitting ? 'Creating...' : 'Create Document'}
              </Button>
              <Button variant="outline" onClick={resetCreateForm}>
                Cancel
              </Button>
            </div>
          </CardContent>
        </Card>
      )}

      {/* Detail panel */}
      {selectedDoc && (
        <Card className="border-primary/30 bg-primary/5">
          <CardHeader className="pb-3 flex flex-row items-center justify-between">
            <CardTitle className="text-lg flex items-center gap-2 min-w-0">
              <div className="shrink-0">{contentTypeIcon(selectedDoc.contentType)}</div>
              <span className="truncate max-w-[400px]">
                {selectedDoc.title || selectedDoc.id.slice(0, 24) + '…'}
              </span>
              <Badge className={contentTypeColor(selectedDoc.contentType)}>
                {selectedDoc.contentType || 'unknown'}
              </Badge>
              {(selectedDoc.chunkCount ?? 0) > 0 && (
                <Badge variant="outline" className="text-xs">
                  {selectedDoc.chunkCount} chunk(s)
                </Badge>
              )}
            </CardTitle>
            <div className="flex items-center gap-2 shrink-0">
              <Button
                variant="destructive"
                size="sm"
                onClick={() => handleDelete(selectedDoc.id, selectedDoc.title)}
              >
                <Trash2 className="h-3.5 w-3.5 mr-1" /> Delete
              </Button>
              <Button variant="ghost" size="sm" onClick={() => setSelectedDocId(null)}>
                <X className="h-4 w-4" />
              </Button>
            </div>
          </CardHeader>
          <CardContent className="space-y-3 text-sm">
            <div className="grid grid-cols-2 gap-4">
              <div>
                <p className="text-xs text-muted-foreground">ID</p>
                <p className="font-mono text-xs truncate">{selectedDoc.id}</p>
              </div>
              <div>
                <p className="text-xs text-muted-foreground">Workspace</p>
                <p className="font-mono text-xs truncate">{selectedDoc.workspaceId || '—'}</p>
              </div>
              <div>
                <p className="text-xs text-muted-foreground">Created</p>
                <p className="flex items-center gap-1">
                  <Clock className="h-3 w-3 text-muted-foreground" />
                  {formatMemoryTimestamp(selectedDoc.createdAt)}
                </p>
              </div>
              <div>
                <p className="text-xs text-muted-foreground">Updated</p>
                <p className="flex items-center gap-1">
                  <Clock className="h-3 w-3 text-muted-foreground" />
                  {formatMemoryTimestamp(selectedDoc.updatedAt)}
                </p>
              </div>
            </div>
            {selectedDoc.sourceUrl && (
              <div>
                <p className="text-xs text-muted-foreground mb-1">Source URL</p>
                <a
                  href={selectedDoc.sourceUrl}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="flex items-center gap-1 text-xs text-primary hover:underline truncate"
                >
                  <ExternalLink className="h-3 w-3 shrink-0" />
                  {selectedDoc.sourceUrl}
                </a>
              </div>
            )}
            {selectedDoc.content && (
              <div>
                <p className="text-xs text-muted-foreground mb-1">
                  Content ({selectedDoc.content.length.toLocaleString()} chars)
                </p>
                <pre className="text-xs bg-muted/50 rounded p-2 overflow-x-auto max-h-48 font-mono whitespace-pre-wrap">
                  {truncateContent(selectedDoc.content, 500)}
                </pre>
              </div>
            )}
            {selectedDoc.metadataJson && selectedDoc.metadataJson !== '{}' && (
              <div>
                <p className="text-xs text-muted-foreground mb-1">Metadata</p>
                <pre className="text-xs bg-muted/50 rounded p-2 overflow-x-auto max-h-24 font-mono">
                  {(() => {
                    try {
                      return JSON.stringify(JSON.parse(selectedDoc.metadataJson), null, 2);
                    } catch {
                      return selectedDoc.metadataJson;
                    }
                  })()}
                </pre>
              </div>
            )}
          </CardContent>
        </Card>
      )}

      {/* Documents list */}
      <Card>
        <CardHeader className="pb-3">
          <CardTitle className="text-lg">All Documents</CardTitle>
        </CardHeader>
        <CardContent>
          {error ? (
            <div className="flex flex-col items-center justify-center py-12 text-center">
              <AlertCircle className="h-8 w-8 mb-2 text-destructive/50" />
              <p className="text-sm text-muted-foreground mb-4">{error}</p>
              <Button variant="outline" size="sm" onClick={() => window.location.reload()}>
                <RefreshCw className="h-3 w-3 mr-2" /> Retry
              </Button>
            </div>
          ) : loading ? (
            <LoadingSkeleton />
          ) : filteredDocs.length === 0 ? (
            <div className="flex flex-col items-center justify-center py-16 text-center text-muted-foreground">
              <FileText className="h-12 w-12 mb-4 opacity-20" />
              <p className="text-lg font-medium">
                {searchQuery || filterType ? 'No matching documents' : 'No documents yet'}
              </p>
              <p className="text-sm mt-1 max-w-sm">
                {searchQuery || filterType
                  ? 'No documents match your filters. Try a different search term or clear the type filter.'
                  : 'Documents are ingested from files, URLs, and pasted content. Create one or upload via CLI.'}
              </p>
              {!searchQuery && !filterType && (
                <Button className="mt-4" onClick={() => setShowCreateForm(true)}>
                  <Plus className="mr-2 h-4 w-4" /> Create First Document
                </Button>
              )}
            </div>
          ) : (
            <div className="space-y-2">
              {filteredDocs.map((doc) => (
                <div
                  key={doc.id}
                  className={`flex items-start justify-between rounded-lg border p-3 transition-colors hover:bg-accent/50 cursor-pointer ${
                    selectedDocId === doc.id
                      ? 'border-primary/50 bg-accent/30'
                      : 'border-border'
                  }`}
                  onClick={() =>
                    setSelectedDocId(selectedDocId === doc.id ? null : doc.id)
                  }
                >
                  <div className="flex items-start gap-3 min-w-0 flex-1 mr-3">
                    <div className="flex h-8 w-8 items-center justify-center rounded bg-muted shrink-0 mt-0.5">
                      {contentTypeIcon(doc.contentType)}
                    </div>
                    <div className="min-w-0">
                      <p className="font-medium truncate max-w-[400px]">
                        {doc.title || doc.id.slice(0, 24) + '…'}
                      </p>
                      <div className="flex items-center gap-2 text-xs text-muted-foreground mt-1">
                        <Clock className="h-3 w-3 shrink-0" />
                        <span>{formatMemoryTimestamp(doc.createdAt)}</span>
                        {(doc.chunkCount ?? 0) > 0 && (
                          <>
                            <span className="text-muted-foreground/50">·</span>
                            <FileText className="h-3 w-3 shrink-0" />
                            <span>{doc.chunkCount} chunk(s)</span>
                          </>
                        )}
                        {doc.sourceUrl && (
                          <>
                            <span className="text-muted-foreground/50">·</span>
                            <Link className="h-3 w-3 shrink-0" />
                            <span className="truncate max-w-[150px]">{doc.sourceUrl}</span>
                          </>
                        )}
                      </div>
                      {doc.content && (
                        <p className="text-xs text-muted-foreground mt-1 line-clamp-1 max-w-[500px]">
                          {truncateContent(doc.content, 100)}
                        </p>
                      )}
                    </div>
                  </div>
                  <div className="flex items-center gap-2 shrink-0 mt-0.5">
                    <Badge variant="outline" className={contentTypeColor(doc.contentType)}>
                      {doc.contentType || 'text'}
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
