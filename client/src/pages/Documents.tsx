import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { FileText, Upload, Plus } from 'lucide-react';

const documents = [
  { id: 'doc-001', name: 'architecture-overview.md', type: 'markdown', size: '28 KB', pages: 1, updated: '2h ago' },
  { id: 'doc-002', name: 'api-specification.yaml', type: 'yaml', size: '14 KB', pages: 1, updated: '5h ago' },
  { id: 'doc-003', name: 'meeting-notes-2025-06-05.txt', type: 'text', size: '4 KB', pages: 1, updated: '1d ago' },
  { id: 'doc-004', name: 'research-paper-embeddings.pdf', type: 'pdf', size: '2.3 MB', pages: 14, updated: '3d ago' },
];

export default function Documents() {
  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-3xl font-bold tracking-tight">Documents</h1>
          <p className="text-muted-foreground">Uploaded documents and their memory embeddings.</p>
        </div>
        <div className="flex gap-2">
          <Button variant="outline" size="sm">
            <Upload className="mr-2 h-4 w-4" />
            Upload
          </Button>
          <Button size="sm">
            <Plus className="mr-2 h-4 w-4" />
            New Document
          </Button>
        </div>
      </div>

      <Card>
        <CardHeader>
          <CardTitle className="text-lg">All Documents</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="space-y-3">
            {documents.map((doc) => (
              <div key={doc.id} className="flex items-center justify-between rounded-lg border border-border p-3">
                <div className="flex items-start gap-3">
                  <FileText className="mt-0.5 h-4 w-4 text-muted-foreground" />
                  <div>
                    <p className="font-medium">{doc.name}</p>
                    <p className="text-xs text-muted-foreground">
                      {doc.size} · {doc.pages} page{doc.pages > 1 ? 's' : ''} · Updated {doc.updated}
                    </p>
                  </div>
                </div>
                <Badge variant="outline">{doc.type}</Badge>
              </div>
            ))}
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
