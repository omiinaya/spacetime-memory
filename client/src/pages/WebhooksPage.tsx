import { useState, useCallback, useEffect } from 'react';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { Tabs, TabsList, TabsTrigger, TabsContent } from '@/components/ui/tabs';
import {
  Globe,
  Plus,
  Trash2,
  AlertCircle,
  RefreshCw,
  Check,
  X,
  Webhook,
  Activity,
  List,
} from 'lucide-react';
import {
  callReducer,
  executeSql,
  parseSqlResponse,
  formatMemoryTimestamp,
} from '@/lib/spacetimedb';

interface WebhookRow {
  webhook_id: string;
  workspace_id: string;
  name: string;
  url: string;
  event_types: string;
  is_active: boolean;
  created_at: string;
  updated_at: string;
  created_by: string;
}

interface WebhookDeliveryRow {
  id: string;
  webhook_id: string;
  workspace_id: string;
  event_type: string;
  payload: string;
  status: string;
  response_code: number;
  response_body: string;
  attempted_at: string;
  delivered_at: string;
  retry_count: number;
}

export default function WebhooksPage() {
  const [webhooks, setWebhooks] = useState<WebhookRow[]>([]);
  const [deliveries, setDeliveries] = useState<WebhookDeliveryRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [successMsg, setSuccessMsg] = useState<string | null>(null);
  const [activeTab, setActiveTab] = useState('webhooks');

  // Create form state
  const [showForm, setShowForm] = useState(false);
  const [newName, setNewName] = useState('');
  const [newUrl, setNewUrl] = useState('');
  const [newEventTypes, setNewEventTypes] = useState('[]');
  const [newSecret, setNewSecret] = useState('');

  // Edit state
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editName, setEditName] = useState('');
  const [editUrl, setEditUrl] = useState('');
  const [editEventTypes, setEditEventTypes] = useState('');
  const [editActive, setEditActive] = useState(true);

  const clearMessages = () => {
    setError(null);
    setSuccessMsg(null);
  };

  const loadWebhooks = useCallback(async () => {
    clearMessages();
    setLoading(true);
    try {
      await callReducer('list_webhooks', ['']);
      const res = await executeSql(
        "SELECT * FROM webhook_list_result WHERE workspace_id = '' ORDER BY created_at ASC"
      );
      const rows = parseSqlResponse<WebhookRow>(res);
      setWebhooks(rows);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load webhooks');
    } finally {
      setLoading(false);
    }
  }, []);

  const loadDeliveries = useCallback(async () => {
    clearMessages();
    setLoading(true);
    try {
      const res = await executeSql(
        'SELECT * FROM webhook_delivery ORDER BY attempted_at DESC LIMIT 100'
      );
      const rows = parseSqlResponse<WebhookDeliveryRow>(res);
      setDeliveries(rows);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load deliveries');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (activeTab === 'webhooks') {
      loadWebhooks();
    } else {
      loadDeliveries();
    }
  }, [activeTab]);

  const handleCreate = useCallback(async () => {
    clearMessages();
    if (!newName.trim() || !newUrl.trim()) {
      setError('Name and URL are required');
      return;
    }
    try {
      await callReducer('create_webhook', ['', newName.trim(), newUrl.trim(), newEventTypes, newSecret]);
      setSuccessMsg('Webhook created');
      setShowForm(false);
      setNewName('');
      setNewUrl('');
      setNewEventTypes('[]');
      setNewSecret('');
      loadWebhooks();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to create webhook');
    }
  }, [newName, newUrl, newEventTypes, newSecret, loadWebhooks]);

  const handleUpdate = useCallback(
    async (webhookId: string) => {
      clearMessages();
      try {
        await callReducer('update_webhook', [webhookId, editName, editUrl, editEventTypes, editActive]);
        setSuccessMsg('Webhook updated');
        setEditingId(null);
        loadWebhooks();
      } catch (err) {
        setError(err instanceof Error ? err.message : 'Failed to update webhook');
      }
    },
    [editName, editUrl, editEventTypes, editActive, loadWebhooks]
  );

  const handleDelete = useCallback(
    async (webhookId: string) => {
      clearMessages();
      try {
        await callReducer('delete_webhook', [webhookId]);
        setSuccessMsg('Webhook deleted');
        loadWebhooks();
      } catch (err) {
        setError(err instanceof Error ? err.message : 'Failed to delete webhook');
      }
    },
    [loadWebhooks]
  );

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-3xl font-bold tracking-tight">Webhooks</h1>
          <p className="text-muted-foreground">
            Manage registered webhooks and view delivery logs.
          </p>
        </div>
        <Button onClick={loadWebhooks} variant="ghost" size="icon">
          <RefreshCw className="h-4 w-4" />
        </Button>
      </div>

      {error && (
        <div className="flex items-center gap-3 rounded-lg border border-destructive/50 bg-destructive/10 p-3 text-destructive text-sm">
          <AlertCircle className="h-5 w-5 shrink-0" />
          <span>{error}</span>
          <button onClick={() => setError(null)} className="ml-auto">
            <X className="h-4 w-4" />
          </button>
        </div>
      )}

      {successMsg && (
        <div className="flex items-center gap-3 rounded-lg border border-green-500/50 bg-green-500/10 p-3 text-green-600 text-sm">
          <Check className="h-5 w-5 shrink-0" />
          <span>{successMsg}</span>
          <button onClick={() => setSuccessMsg(null)} className="ml-auto">
            <X className="h-4 w-4" />
          </button>
        </div>
      )}

      <Tabs value={activeTab} onValueChange={setActiveTab}>
        <TabsList>
          <TabsTrigger value="webhooks">
            <Webhook className="h-4 w-4 mr-1.5" />
            Webhooks
          </TabsTrigger>
          <TabsTrigger value="deliveries">
            <Activity className="h-4 w-4 mr-1.5" />
            Delivery Log
          </TabsTrigger>
        </TabsList>

        <TabsContent value="webhooks">
          {!showForm && (
            <Button onClick={() => setShowForm(true)}>
              <Plus className="h-4 w-4 mr-1.5" />
              Create Webhook
            </Button>
          )}

          {showForm && (
            <Card>
              <CardHeader>
                <CardTitle className="text-lg">New Webhook</CardTitle>
              </CardHeader>
              <CardContent className="space-y-3">
                <div>
                  <label className="text-xs font-medium mb-1 block text-muted-foreground">
                    Name *
                  </label>
                  <Input
                    placeholder="My Webhook"
                    value={newName}
                    onChange={(e) => setNewName(e.target.value)}
                  />
                </div>
                <div>
                  <label className="text-xs font-medium mb-1 block text-muted-foreground">
                    URL *
                  </label>
                  <Input
                    placeholder="https://example.com/webhook"
                    value={newUrl}
                    onChange={(e) => setNewUrl(e.target.value)}
                  />
                </div>
                <div>
                  <label className="text-xs font-medium mb-1 block text-muted-foreground">
                    Event Types (JSON array)
                  </label>
                  <Input
                    placeholder='["message.created", "memory.created"]'
                    value={newEventTypes}
                    onChange={(e) => setNewEventTypes(e.target.value)}
                  />
                  <p className="text-xs text-muted-foreground mt-1">
                    Leave as [] to match all events.
                  </p>
                </div>
                <div>
                  <label className="text-xs font-medium mb-1 block text-muted-foreground">
                    Secret (optional)
                  </label>
                  <Input
                    placeholder="HMAC signing secret"
                    value={newSecret}
                    onChange={(e) => setNewSecret(e.target.value)}
                  />
                </div>
                <div className="flex gap-2 pt-2">
                  <Button onClick={handleCreate}>Create</Button>
                  <Button variant="outline" onClick={() => setShowForm(false)}>
                    Cancel
                  </Button>
                </div>
              </CardContent>
            </Card>
          )}

          <div className="mt-4 space-y-3">
            {loading ? (
              <div className="space-y-3">
                {Array.from({ length: 3 }).map((_, i) => (
                  <div
                    key={i}
                    className="flex items-center justify-between rounded-lg border border-border p-3"
                  >
                    <div className="space-y-1 flex-1">
                      <div className="h-4 w-48 rounded bg-muted animate-pulse" />
                      <div className="h-3 w-64 rounded bg-muted animate-pulse" />
                    </div>
                    <div className="h-6 w-16 rounded-full bg-muted animate-pulse" />
                  </div>
                ))}
              </div>
            ) : webhooks.length === 0 ? (
              <div className="flex flex-col items-center justify-center py-12 text-muted-foreground">
                <Webhook className="h-10 w-10 mb-3 opacity-30" />
                <p className="font-medium">No webhooks registered</p>
                <p className="text-sm mt-1">
                  Create a webhook to receive POST notifications on workspace events.
                </p>
              </div>
            ) : (
              webhooks.map((wh) => {
                const isEditing = editingId === wh.webhook_id;
                return (
                  <div
                    key={wh.webhook_id}
                    className="rounded-lg border border-border p-4"
                  >
                    {isEditing ? (
                      <div className="space-y-3">
                        <Input
                          value={editName}
                          onChange={(e) => setEditName(e.target.value)}
                          placeholder="Name"
                          className="h-8 text-sm"
                        />
                        <Input
                          value={editUrl}
                          onChange={(e) => setEditUrl(e.target.value)}
                          placeholder="URL"
                          className="h-8 text-sm"
                        />
                        <Input
                          value={editEventTypes}
                          onChange={(e) => setEditEventTypes(e.target.value)}
                          placeholder='["event.type"]'
                          className="h-8 text-sm"
                        />
                        <div className="flex items-center gap-2">
                          <label className="text-xs font-medium flex items-center gap-1.5 cursor-pointer">
                            <input
                              type="checkbox"
                              checked={editActive}
                              onChange={(e) => setEditActive(e.target.checked)}
                              className="h-4 w-4 rounded"
                            />
                            Active
                          </label>
                        </div>
                        <div className="flex gap-1">
                          <Button
                            size="sm"
                            onClick={() => handleUpdate(wh.webhook_id)}
                          >
                            Save
                          </Button>
                          <Button
                            size="sm"
                            variant="outline"
                            onClick={() => setEditingId(null)}
                          >
                            Cancel
                          </Button>
                        </div>
                      </div>
                    ) : (
                      <>
                        <div className="flex items-start justify-between">
                          <div className="min-w-0 flex-1 mr-3">
                            <div className="flex items-center gap-2">
                              <h3 className="font-medium text-sm">
                                {wh.name}
                              </h3>
                              <Badge
                                variant={wh.is_active ? 'default' : 'secondary'}
                                className="text-xs"
                              >
                                {wh.is_active ? 'Active' : 'Inactive'}
                              </Badge>
                            </div>
                            <p className="text-xs text-muted-foreground mt-1 font-mono truncate">
                              {wh.url}
                            </p>
                            <div className="flex items-center gap-2 mt-1.5 text-xs text-muted-foreground">
                              <span>
                                Events:{' '}
                                {wh.event_types === '[]'
                                  ? 'All'
                                  : wh.event_types}
                              </span>
                              <span>·</span>
                              <span>
                                Created {formatMemoryTimestamp(wh.created_at)}
                              </span>
                            </div>
                          </div>
                          <div className="flex items-center gap-1 shrink-0">
                            <Button
                              variant="ghost"
                              size="icon"
                              className="h-7 w-7"
                              onClick={() => {
                                setEditingId(wh.webhook_id);
                                setEditName(wh.name);
                                setEditUrl(wh.url);
                                setEditEventTypes(wh.event_types);
                                setEditActive(wh.is_active);
                              }}
                            >
                              <Globe className="h-3.5 w-3.5" />
                            </Button>
                            <Button
                              variant="ghost"
                              size="icon"
                              className="h-7 w-7 text-destructive hover:text-destructive"
                              onClick={() => handleDelete(wh.webhook_id)}
                            >
                              <Trash2 className="h-3.5 w-3.5" />
                            </Button>
                          </div>
                        </div>
                      </>
                    )}
                  </div>
                );
              })
            )}
          </div>
        </TabsContent>

        <TabsContent value="deliveries">
          <Card>
            <CardHeader>
              <CardTitle className="text-lg">Webhook Delivery Log</CardTitle>
            </CardHeader>
            <CardContent>
              {loading ? (
                <div className="space-y-3">
                  {Array.from({ length: 5 }).map((_, i) => (
                    <div
                      key={i}
                      className="h-12 rounded-lg bg-muted animate-pulse"
                    />
                  ))}
                </div>
              ) : deliveries.length === 0 ? (
                <div className="flex flex-col items-center justify-center py-12 text-muted-foreground">
                  <List className="h-10 w-10 mb-3 opacity-30" />
                  <p className="font-medium">No deliveries yet</p>
                  <p className="text-sm mt-1">
                    Webhook deliveries will appear here when events fire.
                  </p>
                </div>
              ) : (
                <div className="space-y-2">
                  {deliveries.map((d) => (
                    <div
                      key={d.id}
                      className="flex items-start justify-between rounded-lg border border-border p-3"
                    >
                      <div className="min-w-0 flex-1 mr-3">
                        <div className="flex items-center gap-2">
                          <Badge
                            variant={
                              d.status === 'delivered'
                                ? 'default'
                                : d.status === 'pending'
                                  ? 'secondary'
                                  : 'destructive'
                            }
                            className="text-xs"
                          >
                            {d.status}
                          </Badge>
                          <span className="text-xs font-medium">
                            {d.event_type}
                          </span>
                        </div>
                        <p className="text-xs text-muted-foreground mt-1">
                          Webhook: {d.webhook_id.slice(0, 12)}…
                          {d.response_code > 0 && (
                            <>
                              {' · '}HTTP {d.response_code}
                            </>
                          )}
                          {d.retry_count > 0 && (
                            <>
                              {' · '}Retries: {d.retry_count}
                            </>
                          )}
                        </p>
                      </div>
                      <span className="text-xs text-muted-foreground shrink-0">
                        {formatMemoryTimestamp(d.attempted_at)}
                      </span>
                    </div>
                  ))}
                </div>
              )}
            </CardContent>
          </Card>
        </TabsContent>
      </Tabs>
    </div>
  );
}
