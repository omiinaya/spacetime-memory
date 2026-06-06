import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Skeleton } from '@/components/ui/skeleton';
import { FileText, AlertCircle, RefreshCw } from 'lucide-react';
import { usePollingQuery, fetchDocuments, formatMemoryTimestamp } from '@/lib/spacetimedb';
import type { DocumentRow } from '@/lib/spacetimedb';

function DocSkeleton() {
  return (
    <div className="space-y-3">
      {Array.from({ length: 4 }).map((_, i) => (
        <div key={i} className="flex items-center justify-between rounded-lg border border-border p-3">
          <div className="space-y-1 flex-1">
            <Skeleton className="h-5 w-56" />
            <Skeleton className="h-3 w-32 mt-1" />
          </div>
          <Skeleton className="h-5 w-16 rounded-full shrink-0 ml-3" />
        </div>
      ))}
    </div>
  );
}

export default function Documents() {
  const { data: docs, loading, error, refetch } = usePollingQuery(() => fetchDocuments(), 10000);

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-3xl font-bold tracking-tight">Documents</h1>
          <p className="text-muted-foreground">
            {loading ? 'Loading...' : `${docs?.length ?? 0} document(s)`}
          </p>
        </div>
        <div className="flex gap-2">
          <Button variant="outline" size="sm" onClick={refetch}>
            <RefreshCw className="mr-2 h-4 w-4" />
            Refresh
          </Button>
        </div>
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
            <DocSkeleton />
          ) : !docs || docs.length === 0 ? (
            <div className="flex flex-col items-center justify-center py-12 text-muted-foreground">
              <FileText className="h-10 w-10 mb-3 opacity-30" />
              <p className="font-medium">No documents yet</p>
              <p className="text-sm mt-1">Upload a document via the CLI or MCP tools.</p>
            </div>
          ) : (
            <div className="space-y-3">
              {(docs as DocumentRow[]).map((doc) => (
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
