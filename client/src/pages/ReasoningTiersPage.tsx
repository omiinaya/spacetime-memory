import { useState, useCallback, useEffect } from 'react';
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import {
  BrainCircuit,
  AlertCircle,
  RefreshCw,
  Check,
  X,
  Star,
  Layers,
  Plus,
  Trash2,
  ArrowLeft,
  Gauge,
  Thermometer,
  Filter,
  Hash,
  ToggleLeft,
  GitBranch,
} from 'lucide-react';
import {
  callReducer,
  executeSql,
  parseSqlResponse,
} from '@/lib/spacetimedb';

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface ReasoningTier {
  id: string;
  workspace_id: string;
  name: string;
  description: string;
  max_tokens: number;
  temperature: number;
  top_p: number;
  max_context_memories: number;
  min_confidence: number;
  requires_reflection: boolean;
  requires_graph_traversal: boolean;
  priority: number;
  is_default: boolean;
  created_at: number;
  updated_at: number;
}

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

// ---------------------------------------------------------------------------
// Page Component
// ---------------------------------------------------------------------------

export default function ReasoningTiersPage() {
  const [tiers, setTiers] = useState<ReasoningTier[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [successMsg, setSuccessMsg] = useState<string | null>(null);

  // Detail view
  const [selectedTier, setSelectedTier] = useState<ReasoningTier | null>(null);

  // Create / Edit form
  const [showForm, setShowForm] = useState(false);
  const [editingTierId, setEditingTierId] = useState<string | null>(null);
  const [formName, setFormName] = useState('');
  const [formDescription, setFormDescription] = useState('');
  const [formMaxTokens, setFormMaxTokens] = useState('1024');
  const [formTemperature, setFormTemperature] = useState('0.7');
  const [formTopP, setFormTopP] = useState('0.9');
  const [formMaxContextMemories, setFormMaxContextMemories] = useState('15');
  const [formMinConfidence, setFormMinConfidence] = useState('0.5');
  const [formRequiresReflection, setFormRequiresReflection] = useState(false);
  const [formRequiresGraphTraversal, setFormRequiresGraphTraversal] = useState(false);
  const [formPriority, setFormPriority] = useState('20');
  const [formIsDefault, setFormIsDefault] = useState(false);
  const [formSubmitting, setFormSubmitting] = useState(false);

  // Apply tier to memory
  const [applyTierId, setApplyTierId] = useState('');
  const [applyMemoryId, setApplyMemoryId] = useState('');
  const [applying, setApplying] = useState(false);

  // Set default loading
  const [actionLoading, setActionLoading] = useState<string | null>(null);

  const clearMessages = () => {
    setError(null);
    setSuccessMsg(null);
  };

  // -----------------------------------------------------------------------
  // Load tiers
  // -----------------------------------------------------------------------

  const loadTiers = useCallback(async () => {

    setLoading(true);
    try {
      await callReducer('get_reasoning_tiers', ['']);
      const res = await executeSql(
        "SELECT * FROM reasoning_tier_result ORDER BY created_at DESC LIMIT 1"
      );
      const rows = parseSqlResponse<{ data: string }>(res);
      if (rows.length > 0 && rows[0].data) {
        try {
          const parsed = JSON.parse(rows[0].data) as ReasoningTier[];
          setTiers(parsed);
          return;
        } catch {
          // fall through
        }
      }
      // Fallback: read from reasoning_tier table directly
      const fallback = await executeSql(
        "SELECT * FROM reasoning_tier ORDER BY priority ASC LIMIT 100"
      );
      setTiers(parseSqlResponse<ReasoningTier>(fallback));
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load reasoning tiers');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    loadTiers();
  }, [loadTiers]);

  // -----------------------------------------------------------------------
  // Select tier detail
  // -----------------------------------------------------------------------

  const selectTier = useCallback((tier: ReasoningTier) => {
    setSelectedTier(tier);
    setShowForm(false);
    setEditingTierId(null);
  }, []);

  const backToList = useCallback(() => {
    setSelectedTier(null);
  }, []);

  // -----------------------------------------------------------------------
  // Create / Edit form helpers
  // -----------------------------------------------------------------------

  const openCreateForm = useCallback(() => {
    setEditingTierId(null);
    setFormName('');
    setFormDescription('');
    setFormMaxTokens('1024');
    setFormTemperature('0.7');
    setFormTopP('0.9');
    setFormMaxContextMemories('15');
    setFormMinConfidence('0.5');
    setFormRequiresReflection(false);
    setFormRequiresGraphTraversal(false);
    setFormPriority('20');
    setFormIsDefault(false);
    setShowForm(true);
    setSelectedTier(null);
  }, []);

  const openEditForm = useCallback((tier: ReasoningTier) => {
    setEditingTierId(tier.id);
    setFormName(tier.name);
    setFormDescription(tier.description);
    setFormMaxTokens(String(tier.max_tokens));
    setFormTemperature(String(tier.temperature));
    setFormTopP(String(tier.top_p));
    setFormMaxContextMemories(String(tier.max_context_memories));
    setFormMinConfidence(String(tier.min_confidence));
    setFormRequiresReflection(tier.requires_reflection);
    setFormRequiresGraphTraversal(tier.requires_graph_traversal);
    setFormPriority(String(tier.priority));
    setFormIsDefault(tier.is_default);
    setShowForm(true);
    setSelectedTier(null);
  }, []);

  // -----------------------------------------------------------------------
  // Submit create / update
  // -----------------------------------------------------------------------

  const handleSubmit = useCallback(async () => {
    clearMessages();
    if (!formName.trim()) {
      setError('Tier name is required');
      return;
    }

    const maxTokens = parseInt(formMaxTokens, 10);
    const temperature = parseFloat(formTemperature);
    const topP = parseFloat(formTopP);
    const maxContextMemories = parseInt(formMaxContextMemories, 10);
    const minConfidence = parseFloat(formMinConfidence);
    const priority = parseInt(formPriority, 10);

    if (isNaN(maxTokens) || maxTokens <= 0) {
      setError('max_tokens must be > 0');
      return;
    }
    if (isNaN(temperature) || temperature < 0 || temperature > 2) {
      setError('temperature must be between 0.0 and 2.0');
      return;
    }
    if (isNaN(topP) || topP < 0 || topP > 1) {
      setError('top_p must be between 0.0 and 1.0');
      return;
    }
    if (isNaN(maxContextMemories) || maxContextMemories <= 0) {
      setError('max_context_memories must be > 0');
      return;
    }
    if (isNaN(minConfidence) || minConfidence < 0 || minConfidence > 1) {
      setError('min_confidence must be between 0.0 and 1.0');
      return;
    }

    setFormSubmitting(true);
    try {
      if (editingTierId) {
        await callReducer('update_reasoning_tier', [
          '',
          editingTierId,
          formName.trim(),
          formDescription.trim(),
          maxTokens,
          temperature,
          topP,
          maxContextMemories,
          minConfidence,
          formRequiresReflection,
          formRequiresGraphTraversal,
          priority,
          formIsDefault,
        ]);
        setSuccessMsg('Reasoning tier updated');
      } else {
        await callReducer('create_reasoning_tier', [
          '',
          '',
          formName.trim(),
          formDescription.trim(),
          maxTokens,
          temperature,
          topP,
          maxContextMemories,
          minConfidence,
          formRequiresReflection,
          formRequiresGraphTraversal,
          priority,
          formIsDefault,
        ]);
        setSuccessMsg('Reasoning tier created');
      }
      setShowForm(false);
      setEditingTierId(null);
      loadTiers();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to save reasoning tier');
    } finally {
      setFormSubmitting(false);
    }
  }, [
    formName, formDescription, formMaxTokens, formTemperature, formTopP,
    formMaxContextMemories, formMinConfidence, formRequiresReflection,
    formRequiresGraphTraversal, formPriority, formIsDefault, editingTierId,
    loadTiers,
  ]);

  // -----------------------------------------------------------------------
  // Set default tier
  // -----------------------------------------------------------------------

  const handleSetDefault = useCallback(
    async (tierId: string) => {
      clearMessages();
      setActionLoading(tierId);
      try {
        await callReducer('set_default_tier', ['', tierId]);
        setSuccessMsg('Default tier updated');
        loadTiers();
      } catch (err) {
        setError(err instanceof Error ? err.message : 'Failed to set default tier');
      } finally {
        setActionLoading(null);
      }
    },
    [loadTiers],
  );

  // -----------------------------------------------------------------------
  // Delete tier
  // -----------------------------------------------------------------------

  const handleDelete = useCallback(
    async (tierId: string) => {
      clearMessages();
      if (!confirm('Delete this reasoning tier?')) return;
      setActionLoading(tierId);
      try {
        await callReducer('delete_reasoning_tier', ['', tierId]);
        setSuccessMsg('Reasoning tier deleted');
        if (selectedTier?.id === tierId) {
          setSelectedTier(null);
        }
        loadTiers();
      } catch (err) {
        setError(err instanceof Error ? err.message : 'Failed to delete tier');
      } finally {
        setActionLoading(null);
      }
    },
    [loadTiers, selectedTier],
  );

  // -----------------------------------------------------------------------
  // Apply tier to memory
  // -----------------------------------------------------------------------

  const handleApplyToMemory = useCallback(async () => {
    clearMessages();
    if (!applyTierId.trim() || !applyMemoryId.trim()) {
      setError('Tier ID and Memory ID are required');
      return;
    }
    setApplying(true);
    try {
      await callReducer('apply_reasoning_tier_to_memory', [
        '',
        applyMemoryId.trim(),
        applyTierId.trim(),
      ]);
      setSuccessMsg(`Tier applied to memory ${applyMemoryId.slice(0, 12)}...`);
      setApplyMemoryId('');
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to apply tier to memory');
    } finally {
      setApplying(false);
    }
  }, [applyTierId, applyMemoryId]);

  // -----------------------------------------------------------------------
  // Render: Detail view
  // -----------------------------------------------------------------------

  if (selectedTier) {
    const t = selectedTier;
    return (
      <div className="space-y-6">
        {/* Header */}
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-3">
            <Button variant="ghost" size="icon" onClick={backToList}>
              <ArrowLeft className="h-5 w-5" />
            </Button>
            <div>
              <h1 className="text-3xl font-bold tracking-tight flex items-center gap-2">
                <BrainCircuit className="h-7 w-7 text-primary" />
                {t.name}
              </h1>
              <p className="text-sm text-muted-foreground">{t.description}</p>
            </div>
          </div>
          <div className="flex items-center gap-2">
            {t.is_default && (
              <Badge className="bg-amber-500/10 text-amber-600 border-amber-500/30">
                <Star className="h-3 w-3 mr-1" />
                Default
              </Badge>
            )}
            <Badge variant="outline">Priority: {t.priority}</Badge>
          </div>
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

        {/* Parameter cards */}
        <div className="grid gap-4 md:grid-cols-3">
          <Card>
            <CardHeader className="pb-2">
              <CardTitle className="text-sm font-medium flex items-center gap-2">
                <Hash className="h-4 w-4 text-blue-500" />
                Max Tokens
              </CardTitle>
            </CardHeader>
            <CardContent>
              <div className="text-2xl font-bold">{t.max_tokens.toLocaleString()}</div>
            </CardContent>
          </Card>
          <Card>
            <CardHeader className="pb-2">
              <CardTitle className="text-sm font-medium flex items-center gap-2">
                <Thermometer className="h-4 w-4 text-red-500" />
                Temperature
              </CardTitle>
            </CardHeader>
            <CardContent>
              <div className="text-2xl font-bold">{t.temperature.toFixed(2)}</div>
            </CardContent>
          </Card>
          <Card>
            <CardHeader className="pb-2">
              <CardTitle className="text-sm font-medium flex items-center gap-2">
                <Filter className="h-4 w-4 text-purple-500" />
                Top-p
              </CardTitle>
            </CardHeader>
            <CardContent>
              <div className="text-2xl font-bold">{t.top_p.toFixed(2)}</div>
            </CardContent>
          </Card>
          <Card>
            <CardHeader className="pb-2">
              <CardTitle className="text-sm font-medium flex items-center gap-2">
                <Layers className="h-4 w-4 text-indigo-500" />
                Context Memories
              </CardTitle>
            </CardHeader>
            <CardContent>
              <div className="text-2xl font-bold">{t.max_context_memories}</div>
            </CardContent>
          </Card>
          <Card>
            <CardHeader className="pb-2">
              <CardTitle className="text-sm font-medium flex items-center gap-2">
                <Gauge className="h-4 w-4 text-emerald-500" />
                Min Confidence
              </CardTitle>
            </CardHeader>
            <CardContent>
              <div className="text-2xl font-bold">{(t.min_confidence * 100).toFixed(0)}%</div>
            </CardContent>
          </Card>
          <Card>
            <CardHeader className="pb-2">
              <CardTitle className="text-sm font-medium">Flags</CardTitle>
            </CardHeader>
            <CardContent>
              <div className="flex flex-wrap gap-2">
                <Badge variant={t.requires_reflection ? 'default' : 'outline'}>
                  <ToggleLeft className="h-3 w-3 mr-1" />
                  Reflection
                </Badge>
                <Badge variant={t.requires_graph_traversal ? 'default' : 'outline'}>
                  <GitBranch className="h-3 w-3 mr-1" />
                  Graph Traversal
                </Badge>
              </div>
            </CardContent>
          </Card>
        </div>

        {/* Actions */}
        <div className="flex flex-wrap gap-2">
          <Button
            onClick={() => { setSelectedTier(null); openEditForm(t); }}
            variant="default"
          >
            Edit
          </Button>
          {!t.is_default && (
            <Button
              onClick={() => handleSetDefault(t.id)}
              disabled={actionLoading === t.id}
              variant="secondary"
            >
              <Star className="h-4 w-4 mr-1.5" />
              Make Default
            </Button>
          )}
          <Button
            onClick={() => handleDelete(t.id)}
            disabled={actionLoading === t.id}
            variant="destructive"
          >
            <Trash2 className="h-4 w-4 mr-1.5" />
            Delete
          </Button>
          <Button variant="outline" onClick={loadTiers}>
            <RefreshCw className="h-4 w-4 mr-1.5" />
            Refresh
          </Button>
        </div>

        {/* Config JSON */}
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm font-medium">Full Configuration</CardTitle>
          </CardHeader>
          <CardContent>
            <pre className="rounded-lg bg-muted p-3 text-xs overflow-x-auto">
              {JSON.stringify(t, null, 2)}
            </pre>
          </CardContent>
        </Card>
      </div>
    );
  }

  // -----------------------------------------------------------------------
  // Render: List view
  // -----------------------------------------------------------------------

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-3xl font-bold tracking-tight flex items-center gap-2">
            <BrainCircuit className="h-7 w-7 text-primary" />
            Reasoning Tiers
          </h1>
          <p className="text-muted-foreground">
            {loading ? 'Loading...' : `${tiers.length} tier(s) configured`}
          </p>
        </div>
        <div className="flex items-center gap-2">
          <Button onClick={openCreateForm}>
            <Plus className="h-4 w-4 mr-1.5" />
            Create Tier
          </Button>
          <Button variant="ghost" size="icon" onClick={loadTiers}>
            <RefreshCw className="h-4 w-4" />
          </Button>
        </div>
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

      {/* Create / Edit Form */}
      {showForm && (
        <Card>
          <CardHeader>
            <CardTitle className="text-lg">
              {editingTierId ? 'Edit Reasoning Tier' : 'Create Reasoning Tier'}
            </CardTitle>
            <CardDescription>
              {editingTierId
                ? 'Update the tier parameters below.'
                : 'Define a new reasoning tier with specific constraints.'}
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
              <div>
                <label className="text-xs font-medium mb-1 block text-muted-foreground">
                  Name *
                </label>
                <input
                  placeholder="e.g. quick, balanced, deep"
                  value={formName}
                  onChange={(e) => setFormName(e.target.value)}
                  className="flex h-10 w-full rounded-md border border-input bg-background px-3 py-2 text-sm ring-offset-background file:border-0 file:bg-transparent file:text-sm file:font-medium placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2"
                />
              </div>
              <div>
                <label className="text-xs font-medium mb-1 block text-muted-foreground">
                  Priority
                </label>
                <input
                  type="number"
                  min="0"
                  value={formPriority}
                  onChange={(e) => setFormPriority(e.target.value)}
                  className="flex h-10 w-full rounded-md border border-input bg-background px-3 py-2 text-sm ring-offset-background file:border-0 file:bg-transparent file:text-sm file:font-medium placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2"
                />
              </div>
            </div>

            <div>
              <label className="text-xs font-medium mb-1 block text-muted-foreground">
                Description
              </label>
              <input
                placeholder="Human-readable description"
                value={formDescription}
                onChange={(e) => setFormDescription(e.target.value)}
                className="flex h-10 w-full rounded-md border border-input bg-background px-3 py-2 text-sm ring-offset-background file:border-0 file:bg-transparent file:text-sm file:font-medium placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2"
              />
            </div>

            <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
              <div>
                <label className="text-xs font-medium mb-1 block text-muted-foreground">
                  Max Tokens
                </label>
                <input
                  type="number"
                  min="1"
                  value={formMaxTokens}
                  onChange={(e) => setFormMaxTokens(e.target.value)}
                  className="flex h-10 w-full rounded-md border border-input bg-background px-3 py-2 text-sm ring-offset-background file:border-0 file:bg-transparent file:text-sm file:font-medium placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2"
                />
              </div>
              <div>
                <label className="text-xs font-medium mb-1 block text-muted-foreground">
                  Temperature
                </label>
                <input
                  type="number"
                  min="0"
                  max="2"
                  step="0.05"
                  value={formTemperature}
                  onChange={(e) => setFormTemperature(e.target.value)}
                  className="flex h-10 w-full rounded-md border border-input bg-background px-3 py-2 text-sm ring-offset-background file:border-0 file:bg-transparent file:text-sm file:font-medium placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2"
                />
              </div>
              <div>
                <label className="text-xs font-medium mb-1 block text-muted-foreground">
                  Top-p
                </label>
                <input
                  type="number"
                  min="0"
                  max="1"
                  step="0.05"
                  value={formTopP}
                  onChange={(e) => setFormTopP(e.target.value)}
                  className="flex h-10 w-full rounded-md border border-input bg-background px-3 py-2 text-sm ring-offset-background file:border-0 file:bg-transparent file:text-sm file:font-medium placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2"
                />
              </div>
              <div>
                <label className="text-xs font-medium mb-1 block text-muted-foreground">
                  Context Memories
                </label>
                <input
                  type="number"
                  min="1"
                  value={formMaxContextMemories}
                  onChange={(e) => setFormMaxContextMemories(e.target.value)}
                  className="flex h-10 w-full rounded-md border border-input bg-background px-3 py-2 text-sm ring-offset-background file:border-0 file:bg-transparent file:text-sm file:font-medium placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2"
                />
              </div>
            </div>

            <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
              <div>
                <label className="text-xs font-medium mb-1 block text-muted-foreground">
                  Min Confidence
                </label>
                <input
                  type="number"
                  min="0"
                  max="1"
                  step="0.05"
                  value={formMinConfidence}
                  onChange={(e) => setFormMinConfidence(e.target.value)}
                  className="flex h-10 w-full rounded-md border border-input bg-background px-3 py-2 text-sm ring-offset-background file:border-0 file:bg-transparent file:text-sm file:font-medium placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2"
                />
              </div>
              <div className="flex items-end pb-2">
                <label className="flex items-center gap-2 cursor-pointer">
                  <input
                    type="checkbox"
                    checked={formRequiresReflection}
                    onChange={(e) => setFormRequiresReflection(e.target.checked)}
                    className="h-4 w-4 rounded border-gray-300 text-primary focus:ring-primary"
                  />
                  <span className="text-sm">Requires Reflection</span>
                </label>
              </div>
              <div className="flex items-end pb-2">
                <label className="flex items-center gap-2 cursor-pointer">
                  <input
                    type="checkbox"
                    checked={formRequiresGraphTraversal}
                    onChange={(e) => setFormRequiresGraphTraversal(e.target.checked)}
                    className="h-4 w-4 rounded border-gray-300 text-primary focus:ring-primary"
                  />
                  <span className="text-sm">Graph Traversal</span>
                </label>
              </div>
              <div className="flex items-end pb-2">
                <label className="flex items-center gap-2 cursor-pointer">
                  <input
                    type="checkbox"
                    checked={formIsDefault}
                    onChange={(e) => setFormIsDefault(e.target.checked)}
                    className="h-4 w-4 rounded border-gray-300 text-primary focus:ring-primary"
                  />
                  <span className="text-sm">Is Default</span>
                </label>
              </div>
            </div>

            <div className="flex gap-2 pt-2">
              <Button onClick={handleSubmit} disabled={formSubmitting}>
                {formSubmitting ? 'Saving...' : editingTierId ? 'Update' : 'Create'}
              </Button>
              <Button variant="outline" onClick={() => { setShowForm(false); setEditingTierId(null); }}>
                Cancel
              </Button>
            </div>
          </CardContent>
        </Card>
      )}

      {/* Apply Tier to Memory */}
      <Card>
        <CardHeader className="pb-3">
          <CardTitle className="text-lg flex items-center gap-2">
            <GitBranch className="h-5 w-5" />
            Apply Tier to Memory
          </CardTitle>
          <CardDescription>
            Tag a memory with a reasoning tier to control how it's processed.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <div className="flex items-end gap-3">
            <div className="flex-1">
              <label className="text-xs font-medium mb-1 block text-muted-foreground">
                Tier ID
              </label>
              <select
                value={applyTierId}
                onChange={(e) => setApplyTierId(e.target.value)}
                className="flex h-10 w-full rounded-md border border-input bg-background px-3 py-2 text-sm ring-offset-background focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2"
              >
                <option value="">Select a tier...</option>
                {tiers.map((t) => (
                  <option key={t.id} value={t.id}>
                    {t.name} ({t.id.slice(0, 8)}...)
                  </option>
                ))}
              </select>
            </div>
            <div className="flex-1">
              <label className="text-xs font-medium mb-1 block text-muted-foreground">
                Memory ID
              </label>
              <input
                placeholder="Enter memory ID"
                value={applyMemoryId}
                onChange={(e) => setApplyMemoryId(e.target.value)}
                className="flex h-10 w-full rounded-md border border-input bg-background px-3 py-2 text-sm ring-offset-background file:border-0 file:bg-transparent file:text-sm file:font-medium placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2"
              />
            </div>
            <Button
              onClick={handleApplyToMemory}
              disabled={!applyTierId || !applyMemoryId.trim() || applying}
            >
              {applying ? 'Applying...' : 'Apply'}
            </Button>
          </div>
        </CardContent>
      </Card>

      {/* Tiers List */}
      <Card>
        <CardHeader>
          <CardTitle className="text-lg">All Tiers</CardTitle>
        </CardHeader>
        <CardContent>
          {loading ? (
            <div className="space-y-3">
              {Array.from({ length: 4 }).map((_, i) => (
                <div
                  key={i}
                  className="flex items-center justify-between rounded-lg border border-border p-4"
                >
                  <div className="space-y-2 flex-1">
                    <div className="h-5 w-24 rounded bg-muted animate-pulse" />
                    <div className="h-3 w-48 rounded bg-muted animate-pulse" />
                  </div>
                  <div className="flex gap-2">
                    <div className="h-7 w-16 rounded-full bg-muted animate-pulse" />
                    <div className="h-7 w-16 rounded-full bg-muted animate-pulse" />
                  </div>
                </div>
              ))}
            </div>
          ) : tiers.length === 0 ? (
            <div className="flex flex-col items-center justify-center py-12 text-muted-foreground">
              <BrainCircuit className="h-10 w-10 mb-3 opacity-30" />
              <p className="font-medium">No reasoning tiers configured</p>
              <p className="text-sm mt-1">Create a tier to get started, or seed defaults from presets.</p>
            </div>
          ) : (
            <div className="space-y-3">
              {tiers.map((tier) => {
                const TierIcon = BrainCircuit;
                return (
                  <div
                    key={tier.id}
                    className="rounded-lg border border-border p-4 hover:bg-accent/30 cursor-pointer transition-colors"
                    onClick={() => selectTier(tier)}
                  >
                    <div className="flex items-start justify-between">
                      <div className="flex items-start gap-3 min-w-0 flex-1">
                        <TierIcon className="h-8 w-8 text-primary shrink-0 mt-1" />
                        <div className="min-w-0">
                          <div className="flex items-center gap-2 mb-1">
                            <span className="font-semibold text-lg capitalize">{tier.name}</span>
                            {tier.is_default && (
                              <Badge className="bg-amber-500/10 text-amber-600 border-amber-500/30 text-xs">
                                <Star className="h-3 w-3 mr-0.5" />
                                Default
                              </Badge>
                            )}
                            <Badge variant="outline" className="text-xs">
                              P{tier.priority}
                            </Badge>
                          </div>
                          <p className="text-sm text-muted-foreground line-clamp-1">
                            {tier.description}
                          </p>
                          <div className="flex flex-wrap gap-1.5 mt-2">
                            <Badge variant="secondary" className="text-[10px]">
                              {tier.max_tokens.toLocaleString()} tokens
                            </Badge>
                            <Badge variant="secondary" className="text-[10px]">
                              T={tier.temperature.toFixed(1)}
                            </Badge>
                            <Badge variant="secondary" className="text-[10px]">
                              p={tier.top_p.toFixed(2)}
                            </Badge>
                            <Badge variant="secondary" className="text-[10px]">
                              {tier.max_context_memories} ctx
                            </Badge>
                          </div>
                        </div>
                      </div>
                      <div className="flex items-center gap-1 shrink-0 ml-3" onClick={(e) => e.stopPropagation()}>
                        <Button
                          variant="ghost"
                          size="sm"
                          onClick={() => openEditForm(tier)}
                        >
                          Edit
                        </Button>
                        {!tier.is_default && (
                          <Button
                            variant="ghost"
                            size="sm"
                            onClick={() => handleSetDefault(tier.id)}
                            disabled={actionLoading === tier.id}
                          >
                            <Star className="h-3.5 w-3.5" />
                          </Button>
                        )}
                        <Button
                          variant="ghost"
                          size="sm"
                          onClick={() => handleDelete(tier.id)}
                          disabled={actionLoading === tier.id}
                          className="text-destructive hover:text-destructive"
                        >
                          <Trash2 className="h-3.5 w-3.5" />
                        </Button>
                      </div>
                    </div>
                  </div>
                );
              })}
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
