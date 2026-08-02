import { useState, useCallback } from 'react';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import {
  Download,
  Upload,
  FileJson,
  FileText,
  Table2,
  AlertCircle,
  Check,
  X,
  RefreshCw,
  Database,
  DownloadCloud,
  UploadCloud,
  Replace,
  Merge,
  SkipForward,
} from 'lucide-react';
import { callReducer, executeSql, parseSqlResponse } from '@/lib/spacetimedb';

export default function ExportImportPage() {
  const [activeTab, setActiveTab] = useState('export');
  const [exportFormat, setExportFormat] = useState('json');
  const [exportData, setExportData] = useState<string | null>(null);
  const [importData, setImportData] = useState('');
  const [importStrategy, setImportStrategy] = useState('merge');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [successMsg, setSuccessMsg] = useState<string | null>(null);

  const clearMessages = () => { setError(null); setSuccessMsg(null); };

  const handleExport = useCallback(async () => {
    clearMessages();
    setLoading(true);
    setExportData(null);
    try {
      const res = await executeSql('SELECT * FROM memory WHERE is_active = true ORDER BY created_at ASC LIMIT 1000');
      const memories = parseSqlResponse<any>(res);
      if (memories.length === 0) {
        setError('No memories found to export');
        setLoading(false);
        return;
      }

      if (exportFormat === 'json') {
        setExportData(JSON.stringify(memories, null, 2));
      } else if (exportFormat === 'csv') {
        const cols = Object.keys(memories[0]);
        const csv = [cols.join(','), ...memories.map(m => cols.map(c => JSON.stringify(String(m[c] ?? ''))).join(','))].join('\n');
        setExportData(csv);
      } else {
        // markdown
        let md = `# Memory Export\n\nExported ${memories.length} memories.\n\n`;
        for (const m of memories) {
          md += `## ${(m.summary || m.content || 'Untitled').slice(0, 80)}\n`;
          md += `- **Type:** ${m.memory_type || 'unknown'}\n`;
          md += `- **Created:** ${m.created_at || 'N/A'}\n`;
          md += `- **Content:** ${(m.content || '').slice(0, 500)}\n\n`;
        }
        setExportData(md);
      }
      setSuccessMsg(`Exported ${memories.length} memories`);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Export failed');
    } finally {
      setLoading(false);
    }
  }, [exportFormat]);

  const handleImport = useCallback(async () => {
    clearMessages();
    if (!importData.trim()) {
      setError('Paste export data first');
      return;
    }
    setLoading(true);
    try {
      let memories: any[];
      try {
        memories = JSON.parse(importData);
      } catch {
        setError('Invalid JSON format');
        setLoading(false);
        return;
      }
      if (!Array.isArray(memories)) {
        setError('Expected an array of memories');
        setLoading(false);
        return;
      }

      let imported = 0;
      let skipped = 0;
      for (const mem of memories) {
        const content = mem.content || '';
        if (!content.trim()) { skipped++; continue; }
        try {
          await callReducer('store_memory', [
            mem.workspace_id || '',
            content,
            mem.memory_type || 'experience',
            mem.tier || 'standard',
            mem.importance || 0.5,
          ]);
          imported++;
        } catch {
          if (importStrategy === 'skip') skipped++;
          else if (importStrategy === 'replace') {
            // Try delete then re-import
            try { await callReducer('deactivate_memory', [mem.id || '']); } catch {}
            try {
              await callReducer('store_memory', [
                mem.workspace_id || '',
                content,
                mem.memory_type || 'experience',
                mem.tier || 'standard',
                mem.importance || 0.5,
              ]);
              imported++;
            } catch { skipped++; }
          } else skipped++;
        }
      }
      setSuccessMsg(`Imported ${imported} memories (${skipped} skipped)`);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Import failed');
    } finally {
      setLoading(false);
    }
  }, [importData, importStrategy]);

  const copyToClipboard = () => {
    if (exportData) {
      navigator.clipboard.writeText(exportData);
      setSuccessMsg('Copied to clipboard');
    }
  };

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-3xl font-bold tracking-tight">Export / Import</h1>
          <p className="text-muted-foreground">
            Export and import memories in JSON, CSV, or Markdown format.
          </p>
        </div>
        <Database className="h-6 w-6 text-muted-foreground" />
      </div>

      {error && (
        <div className="flex items-center gap-3 rounded-lg border border-destructive/50 bg-destructive/10 p-3 text-destructive text-sm">
          <AlertCircle className="h-5 w-5 shrink-0" />
          <span>{error}</span>
          <button onClick={() => setError(null)} className="ml-auto"><X className="h-4 w-4" /></button>
        </div>
      )}
      {successMsg && (
        <div className="flex items-center gap-3 rounded-lg border border-green-500/50 bg-green-500/10 p-3 text-green-600 text-sm">
          <Check className="h-5 w-5 shrink-0" />
          <span>{successMsg}</span>
          <button onClick={() => setSuccessMsg(null)} className="ml-auto"><X className="h-4 w-4" /></button>
        </div>
      )}

      <Tabs value={activeTab} onValueChange={setActiveTab}>
        <TabsList>
          <TabsTrigger value="export"><DownloadCloud className="h-4 w-4 mr-1.5" />Export</TabsTrigger>
          <TabsTrigger value="import"><UploadCloud className="h-4 w-4 mr-1.5" />Import</TabsTrigger>
        </TabsList>

        <TabsContent value="export" className="space-y-4">
          <Card>
            <CardHeader>
              <CardTitle className="text-lg flex items-center gap-2"><Download className="h-4 w-4" />Export Memories</CardTitle>
            </CardHeader>
            <CardContent className="space-y-4">
              <div className="flex items-center gap-2">
                <span className="text-sm font-medium">Format:</span>
                {['json', 'csv', 'markdown'].map(fmt => (
                  <Button
                    key={fmt}
                    variant={exportFormat === fmt ? 'default' : 'outline'}
                    size="sm"
                    onClick={() => setExportFormat(fmt)}
                  >
                    {fmt === 'json' ? <FileJson className="h-3.5 w-3.5 mr-1" /> :
                     fmt === 'csv' ? <Table2 className="h-3.5 w-3.5 mr-1" /> :
                     <FileText className="h-3.5 w-3.5 mr-1" />}
                    {fmt.toUpperCase()}
                  </Button>
                ))}
              </div>
              <Button onClick={handleExport} disabled={loading}>
                {loading ? <RefreshCw className="h-4 w-4 mr-1.5 animate-spin" /> : <Download className="h-4 w-4 mr-1.5" />}
                Export
              </Button>
              {exportData && (
                <div className="space-y-2">
                  <div className="flex items-center justify-between">
                    <span className="text-xs text-muted-foreground">{exportData.length.toLocaleString()} chars</span>
                    <Button variant="ghost" size="sm" onClick={copyToClipboard}>
                      Copy
                    </Button>
                  </div>
                  <pre className="max-h-96 overflow-auto rounded-lg border border-border bg-muted/30 p-4 text-xs font-mono">
                    {exportData.slice(0, 5000)}
                    {exportData.length > 5000 && '\n... (truncated)'}
                  </pre>
                </div>
              )}
            </CardContent>
          </Card>
        </TabsContent>

        <TabsContent value="import" className="space-y-4">
          <Card>
            <CardHeader>
              <CardTitle className="text-lg flex items-center gap-2"><Upload className="h-4 w-4" />Import Memories</CardTitle>
            </CardHeader>
            <CardContent className="space-y-4">
              <div className="flex items-center gap-2">
                <span className="text-sm font-medium">Strategy:</span>
                {[
                  { value: 'merge', label: 'Merge', icon: Merge },
                  { value: 'replace', label: 'Replace', icon: Replace },
                  { value: 'skip', label: 'Skip', icon: SkipForward },
                ].map(s => (
                  <Button
                    key={s.value}
                    variant={importStrategy === s.value ? 'default' : 'outline'}
                    size="sm"
                    onClick={() => setImportStrategy(s.value)}
                  >
                    <s.icon className="h-3.5 w-3.5 mr-1" />
                    {s.label}
                  </Button>
                ))}
              </div>
              <div>
                <label className="text-xs font-medium mb-1 block text-muted-foreground">
                  Paste JSON export data
                </label>
                <textarea
                  className="w-full min-h-[200px] rounded-lg border border-border bg-background p-3 text-sm font-mono focus:outline-none focus:ring-2 focus:ring-primary"
                  placeholder='[{"content": "..."}, ...]'
                  value={importData}
                  onChange={(e) => setImportData(e.target.value)}
                />
              </div>
              <Button onClick={handleImport} disabled={loading}>
                {loading ? <RefreshCw className="h-4 w-4 mr-1.5 animate-spin" /> : <Upload className="h-4 w-4 mr-1.5" />}
                Import
              </Button>
            </CardContent>
          </Card>
        </TabsContent>
      </Tabs>
    </div>
  );
}
