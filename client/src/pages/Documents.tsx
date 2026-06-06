import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { FileText, AlertCircle } from 'lucide-react';
import { useTable } from '@/lib/useReactiveDb';
import { formatMemoryTimestamp } from '@/lib/spacetimedb';

interface DocumentRow {
  id: string;
  workspace_id: string;
  title: string;
  content_type: string;
  created_at: string | null;
  updated_at: string | null;
}

export default function Documents() {
  const { data: docs, loading, error } = useTable<DocumentRow>('document');

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-3xl font-bold tracking-tight">Documents</h1>
        <p className="text-muted-foreground">
          {loading ? 'Loading...' : `${docs.length} document(s)`}
        </p>
      </div>

      <Card>
        <CardHeader>
          <CardTitle className="text-lg">All Documents</CardTitle>
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
                    <div className="h-5 w-56 rounded bg-muted animate-pulse" />
                    <div className="h-3 w-32 mt-1 rounded bg-muted animate-pulse" />
                  </div>
                  <div className="h-5 w-16 rounded-full bg-muted animate-pulse shrink-0 ml-3" />
                </div>
              ))}
            </div>
          ) : docs.length === 0 ? (
            <div className="flex flex-col items-center justify-center py-12 text-muted-foreground">
              <FileText className="h-10 w-10 mb-3 opacity-30" />
              <p className="font-medium">No documents yet</p>
              <p className="text-sm mt-1">Upload a document via the CLI or MCP tools.</p>
            </div>
          ) : (
            <div className="space-y-3">
              {docs.map((doc) => (
                <div key={doc.id} className="flex items-center justify-between rounded-lg border border-border p-3">
                  <div className="flex items-start gap-3 min-w-0 flex-1 mr-3">
                    <FileText className="mt-0.5 h-4 w-4 text-muted-foreground shrink-0" />
                    <div className="min-w-0">
                      <p className="font-medium truncate max-w-[400px]">{doc.title || doc.id.slice(0, 24)}</p>
                      <p className="text-xs text-muted-foreground">
                        {doc.content_type || 'text'} · Updated {formatMemoryTimestamp(doc.updated_at ?? doc.created_at)}
                      </p>
                    </div>
                  </div>
                  <div className="flex items-center gap-3 shrink-0">
                    <Badge variant="outline">{doc.content_type || 'text'}</Badge>
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
