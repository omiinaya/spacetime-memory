import { useState, useCallback, useEffect } from 'react';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { Tabs, TabsList, TabsTrigger, TabsContent } from '@/components/ui/tabs';
import {
  Plus,
  Trash2,
  AlertCircle,
  RefreshCw,
  Check,
  X,
  Layers,
  Share2,
  Search,
  Play,
} from 'lucide-react';
import {
  callReducer,
  executeSql,
  parseSqlResponse,
  formatMemoryTimestamp,
} from '@/lib/spacetimedb';

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface MemoryRow {
  id: string;
  workspace_id: string;
  content: string;
  summary: string;
  memory_type: string;
  tier: string;
  importance: number;
  is_active: boolean;
  created_at: string;
  updated_at: string;
}

interface EntityTypeContent {
  name: string;
  parent?: string;
  properties?: Record<string, unknown>;
  description?: string;
}

interface RelationTypeContent {
  name: string;
  sourceTypes: string[];
  targetTypes: string[];
  properties?: Record<string, unknown>;
  description?: string;
}

interface SearchRecipeContent {
  name: string;
  queryTemplate: string;
  filters?: Record<string, unknown>;
  description?: string;
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function parseEntityTypeContent(content: string): EntityTypeContent {
  try {
    const parsed = JSON.parse(content);
    return {
      name: parsed.name || 'Unnamed',
      parent: parsed.parent || undefined,
      properties: parsed.properties || undefined,
      description: parsed.description || undefined,
    };
  } catch {
    return { name: 'Unnamed' };
  }
}

function parseRelationTypeContent(content: string): RelationTypeContent {
  try {
    const parsed = JSON.parse(content);
    return {
      name: parsed.name || 'Unnamed',
      sourceTypes: Array.isArray(parsed.sourceTypes) ? parsed.sourceTypes : [],
      targetTypes: Array.isArray(parsed.targetTypes) ? parsed.targetTypes : [],
      properties: parsed.properties || undefined,
      description: parsed.description || undefined,
    };
  } catch {
    return { name: 'Unnamed', sourceTypes: [], targetTypes: [] };
  }
}

function parseRecipeContent(content: string): SearchRecipeContent {
  try {
    const parsed = JSON.parse(content);
    return {
      name: parsed.name || 'Unnamed Recipe',
      queryTemplate: parsed.queryTemplate || '',
      filters: parsed.filters || undefined,
      description: parsed.description || undefined,
    };
  } catch {
    return { name: 'Unnamed Recipe', queryTemplate: '' };
  }
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export default function OntologyPage() {
  const [entityTypes, setEntityTypes] = useState<MemoryRow[]>([]);
  const [relationTypes, setRelationTypes] = useState<MemoryRow[]>([]);
  const [recipes, setRecipes] = useState<MemoryRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [successMsg, setSuccessMsg] = useState<string | null>(null);
  const [activeTab, setActiveTab] = useState('entity-types');

  // Entity type form
  const [showEntityForm, setShowEntityForm] = useState(false);
  const [newEntityName, setNewEntityName] = useState('');
  const [newEntityParent, setNewEntityParent] = useState('');
  const [newEntityProperties, setNewEntityProperties] = useState('{}');
  const [newEntityDescription, setNewEntityDescription] = useState('');

  // Relation type form
  const [showRelationForm, setShowRelationForm] = useState(false);
  const [newRelationName, setNewRelationName] = useState('');
  const [newRelationSourceTypes, setNewRelationSourceTypes] = useState('');
  const [newRelationTargetTypes, setNewRelationTargetTypes] = useState('');
  const [newRelationProperties, setNewRelationProperties] = useState('{}');
  const [newRelationDescription, setNewRelationDescription] = useState('');

  // Recipe form
  const [showRecipeForm, setShowRecipeForm] = useState(false);
  const [newRecipeName, setNewRecipeName] = useState('');
  const [newRecipeQueryTemplate, setNewRecipeQueryTemplate] = useState('');
  const [newRecipeFilters, setNewRecipeFilters] = useState('{}');
  const [newRecipeDescription, setNewRecipeDescription] = useState('');

  const clearMessages = () => {
    setError(null);
    setSuccessMsg(null);
  };

  // -----------------------------------------------------------------------
  // Load data
  // -----------------------------------------------------------------------

  const loadEntityTypes = useCallback(async () => {
    clearMessages();
    setLoading(true);
    try {
      const res = await executeSql(
        "SELECT * FROM memory WHERE memory_type = 'entity_type' AND is_active = true ORDER BY created_at ASC",
      );
      const rows = parseSqlResponse<MemoryRow>(res);
      setEntityTypes(rows);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load entity types');
    } finally {
      setLoading(false);
    }
  }, []);

  const loadRelationTypes = useCallback(async () => {
    clearMessages();
    setLoading(true);
    try {
      const res = await executeSql(
        "SELECT * FROM memory WHERE memory_type = 'relation_type' AND is_active = true ORDER BY created_at ASC",
      );
      const rows = parseSqlResponse<MemoryRow>(res);
      setRelationTypes(rows);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load relation types');
    } finally {
      setLoading(false);
    }
  }, []);

  const loadRecipes = useCallback(async () => {
    clearMessages();
    setLoading(true);
    try {
      const res = await executeSql(
        "SELECT * FROM memory WHERE memory_type = 'search_recipe' AND is_active = true ORDER BY created_at ASC",
      );
      const rows = parseSqlResponse<MemoryRow>(res);
      setRecipes(rows);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load search recipes');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (activeTab === 'entity-types') {
      loadEntityTypes();
    } else if (activeTab === 'relation-types') {
      loadRelationTypes();
    } else {
      loadRecipes();
    }
  }, [activeTab, loadEntityTypes, loadRelationTypes, loadRecipes]);

  // -----------------------------------------------------------------------
  // Entity Type CRUD
  // -----------------------------------------------------------------------

  const handleCreateEntityType = useCallback(async () => {
    clearMessages();
    if (!newEntityName.trim()) {
      setError('Entity type name is required');
      return;
    }
    try {
      const content = JSON.stringify({
        name: newEntityName.trim(),
        parent: newEntityParent.trim() || undefined,
        properties: JSON.parse(newEntityProperties || '{}'),
        description: newEntityDescription.trim() || undefined,
      });
      await callReducer('store_memory', ['', content, 'entity_type', 'standard', 0.5]);
      setSuccessMsg('Entity type created');
      setShowEntityForm(false);
      setNewEntityName('');
      setNewEntityParent('');
      setNewEntityProperties('{}');
      setNewEntityDescription('');
      loadEntityTypes();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to create entity type');
    }
  }, [newEntityName, newEntityParent, newEntityProperties, newEntityDescription, loadEntityTypes]);

  const handleDeleteEntityType = useCallback(
    async (id: string) => {
      clearMessages();
      try {
        await callReducer('deactivate_memory', [id]);
        setSuccessMsg('Entity type deleted');
        loadEntityTypes();
      } catch (err) {
        setError(err instanceof Error ? err.message : 'Failed to delete entity type');
      }
    },
    [loadEntityTypes],
  );

  // -----------------------------------------------------------------------
  // Relation Type CRUD
  // -----------------------------------------------------------------------

  const handleCreateRelationType = useCallback(async () => {
    clearMessages();
    if (!newRelationName.trim()) {
      setError('Relation type name is required');
      return;
    }
    const sourceTypes = newRelationSourceTypes
      .split(',')
      .map((s) => s.trim())
      .filter(Boolean);
    const targetTypes = newRelationTargetTypes
      .split(',')
      .map((s) => s.trim())
      .filter(Boolean);
    if (sourceTypes.length === 0 || targetTypes.length === 0) {
      setError('At least one source type and one target type are required');
      return;
    }
    try {
      const content = JSON.stringify({
        name: newRelationName.trim(),
        sourceTypes,
        targetTypes,
        properties: JSON.parse(newRelationProperties || '{}'),
        description: newRelationDescription.trim() || undefined,
      });
      await callReducer('store_memory', ['', content, 'relation_type', 'standard', 0.5]);
      setSuccessMsg('Relation type created');
      setShowRelationForm(false);
      setNewRelationName('');
      setNewRelationSourceTypes('');
      setNewRelationTargetTypes('');
      setNewRelationProperties('{}');
      setNewRelationDescription('');
      loadRelationTypes();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to create relation type');
    }
  }, [
    newRelationName,
    newRelationSourceTypes,
    newRelationTargetTypes,
    newRelationProperties,
    newRelationDescription,
    loadRelationTypes,
  ]);

  const handleDeleteRelationType = useCallback(
    async (id: string) => {
      clearMessages();
      try {
        await callReducer('deactivate_memory', [id]);
        setSuccessMsg('Relation type deleted');
        loadRelationTypes();
      } catch (err) {
        setError(err instanceof Error ? err.message : 'Failed to delete relation type');
      }
    },
    [loadRelationTypes],
  );

  // -----------------------------------------------------------------------
  // Recipe CRUD
  // -----------------------------------------------------------------------

  const handleCreateRecipe = useCallback(async () => {
    clearMessages();
    if (!newRecipeName.trim() || !newRecipeQueryTemplate.trim()) {
      setError('Recipe name and query template are required');
      return;
    }
    try {
      const content = JSON.stringify({
        name: newRecipeName.trim(),
        queryTemplate: newRecipeQueryTemplate.trim(),
        filters: JSON.parse(newRecipeFilters || '{}'),
        description: newRecipeDescription.trim() || undefined,
      });
      await callReducer('store_memory', ['', content, 'search_recipe', 'standard', 0.5]);
      setSuccessMsg('Search recipe created');
      setShowRecipeForm(false);
      setNewRecipeName('');
      setNewRecipeQueryTemplate('');
      setNewRecipeFilters('{}');
      setNewRecipeDescription('');
      loadRecipes();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to create search recipe');
    }
  }, [newRecipeName, newRecipeQueryTemplate, newRecipeFilters, newRecipeDescription, loadRecipes]);

  const handleExecuteRecipe = useCallback(
    async (recipeId: string) => {
      clearMessages();
      try {
        // Execute by storing a search execution marker; the backend picks it up
        await callReducer('store_memory', [
          '',
          JSON.stringify({ recipe_id: recipeId, status: 'queued', queued_at: new Date().toISOString() }),
          'recipe_execution',
          'standard',
          0.5,
        ]);
        setSuccessMsg('Recipe queued for execution');
      } catch (err) {
        setError(err instanceof Error ? err.message : 'Failed to execute recipe');
      }
    },
    [],
  );

  const handleDeleteRecipe = useCallback(
    async (id: string) => {
      clearMessages();
      try {
        await callReducer('deactivate_memory', [id]);
        setSuccessMsg('Search recipe deleted');
        loadRecipes();
      } catch (err) {
        setError(err instanceof Error ? err.message : 'Failed to delete search recipe');
      }
    },
    [loadRecipes],
  );

  // -----------------------------------------------------------------------
  // Render helpers
  // -----------------------------------------------------------------------

  const renderError = () =>
    error ? (
      <div className="flex items-center gap-3 rounded-lg border border-destructive/50 bg-destructive/10 p-3 text-destructive text-sm">
        <AlertCircle className="h-5 w-5 shrink-0" />
        <span>{error}</span>
        <button onClick={() => setError(null)} className="ml-auto">
          <X className="h-4 w-4" />
        </button>
      </div>
    ) : null;

  const renderSuccess = () =>
    successMsg ? (
      <div className="flex items-center gap-3 rounded-lg border border-green-500/50 bg-green-500/10 p-3 text-green-600 text-sm">
        <Check className="h-5 w-5 shrink-0" />
        <span>{successMsg}</span>
        <button onClick={() => setSuccessMsg(null)} className="ml-auto">
          <X className="h-4 w-4" />
        </button>
      </div>
    ) : null;

  const renderLoadingSkeleton = (count = 3) => (
    <div className="space-y-3">
      {Array.from({ length: count }).map((_, i) => (
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
  );

  const renderEmptyState = (icon: React.ReactNode, title: string, description: string) => (
    <div className="flex flex-col items-center justify-center py-12 text-muted-foreground">
      {icon}
      <p className="font-medium">{title}</p>
      <p className="text-sm mt-1">{description}</p>
    </div>
  );

  // -----------------------------------------------------------------------
  // Tab: Entity Types
  // -----------------------------------------------------------------------

  const renderEntityTypesTab = () => (
    <TabsContent value="entity-types">
      {!showEntityForm && (
        <Button onClick={() => setShowEntityForm(true)}>
          <Plus className="h-4 w-4 mr-1.5" />
          Create Entity Type
        </Button>
      )}

      {showEntityForm && (
        <Card>
          <CardHeader>
            <CardTitle className="text-lg">New Entity Type</CardTitle>
          </CardHeader>
          <CardContent className="space-y-3">
            <div>
              <label className="text-xs font-medium mb-1 block text-muted-foreground">
                Name *
              </label>
              <Input
                placeholder="Person, Organization, Document, ..."
                value={newEntityName}
                onChange={(e) => setNewEntityName(e.target.value)}
              />
            </div>
            <div>
              <label className="text-xs font-medium mb-1 block text-muted-foreground">
                Parent Type
              </label>
              <Input
                placeholder="Leave empty for root type"
                value={newEntityParent}
                onChange={(e) => setNewEntityParent(e.target.value)}
              />
              <p className="text-xs text-muted-foreground mt-1">
                Name of an existing entity type to inherit from.
              </p>
            </div>
            <div>
              <label className="text-xs font-medium mb-1 block text-muted-foreground">
                Properties (JSON)
              </label>
              <Input
                placeholder='{"name": "string", "age": "number"}'
                value={newEntityProperties}
                onChange={(e) => setNewEntityProperties(e.target.value)}
              />
            </div>
            <div>
              <label className="text-xs font-medium mb-1 block text-muted-foreground">
                Description
              </label>
              <Input
                placeholder="Optional description"
                value={newEntityDescription}
                onChange={(e) => setNewEntityDescription(e.target.value)}
              />
            </div>
            <div className="flex gap-2 pt-2">
              <Button onClick={handleCreateEntityType}>Create</Button>
              <Button variant="outline" onClick={() => setShowEntityForm(false)}>
                Cancel
              </Button>
            </div>
          </CardContent>
        </Card>
      )}

      <div className="mt-4 space-y-3">
        {loading ? (
          renderLoadingSkeleton(3)
        ) : entityTypes.length === 0 ? (
          renderEmptyState(
            <Layers className="h-10 w-10 mb-3 opacity-30" />,
            'No entity types defined',
            'Create an entity type to start building your ontology.',
          )
        ) : (
          entityTypes.map((et) => {
            const parsed = parseEntityTypeContent(et.content);
            const propCount = parsed.properties
              ? Object.keys(parsed.properties).length
              : 0;
            return (
              <div
                key={et.id}
                className="rounded-lg border border-border p-4"
              >
                <div className="flex items-start justify-between">
                  <div className="min-w-0 flex-1 mr-3">
                    <div className="flex items-center gap-2">
                      <h3 className="font-medium text-sm">{parsed.name}</h3>
                      {parsed.parent && (
                        <Badge variant="secondary" className="text-xs">
                          extends {parsed.parent}
                        </Badge>
                      )}
                    </div>
                    <div className="flex items-center gap-2 mt-1.5 text-xs text-muted-foreground">
                      {parsed.description && (
                        <span className="truncate max-w-[300px]">
                          {parsed.description}
                        </span>
                      )}
                      {propCount > 0 && (
                        <>
                          {parsed.description && <span>·</span>}
                          <span>{propCount} propert{propCount === 1 ? 'y' : 'ies'}</span>
                        </>
                      )}
                      <span>·</span>
                      <span>Created {formatMemoryTimestamp(et.created_at)}</span>
                    </div>
                  </div>
                  <div className="flex items-center gap-1 shrink-0">
                    <Button
                      variant="ghost"
                      size="icon"
                      className="h-7 w-7 text-destructive hover:text-destructive"
                      onClick={() => handleDeleteEntityType(et.id)}
                    >
                      <Trash2 className="h-3.5 w-3.5" />
                    </Button>
                  </div>
                </div>
              </div>
            );
          })
        )}
      </div>
    </TabsContent>
  );

  // -----------------------------------------------------------------------
  // Tab: Relation Types
  // -----------------------------------------------------------------------

  const renderRelationTypesTab = () => (
    <TabsContent value="relation-types">
      {!showRelationForm && (
        <Button onClick={() => setShowRelationForm(true)}>
          <Plus className="h-4 w-4 mr-1.5" />
          Create Relation Type
        </Button>
      )}

      {showRelationForm && (
        <Card>
          <CardHeader>
            <CardTitle className="text-lg">New Relation Type</CardTitle>
          </CardHeader>
          <CardContent className="space-y-3">
            <div>
              <label className="text-xs font-medium mb-1 block text-muted-foreground">
                Name *
              </label>
              <Input
                placeholder="works_at, authored_by, belongs_to, ..."
                value={newRelationName}
                onChange={(e) => setNewRelationName(e.target.value)}
              />
            </div>
            <div>
              <label className="text-xs font-medium mb-1 block text-muted-foreground">
                Source Types *
              </label>
              <Input
                placeholder="Person, Organization"
                value={newRelationSourceTypes}
                onChange={(e) => setNewRelationSourceTypes(e.target.value)}
              />
              <p className="text-xs text-muted-foreground mt-1">
                Comma-separated entity type names.
              </p>
            </div>
            <div>
              <label className="text-xs font-medium mb-1 block text-muted-foreground">
                Target Types *
              </label>
              <Input
                placeholder="Company, Project"
                value={newRelationTargetTypes}
                onChange={(e) => setNewRelationTargetTypes(e.target.value)}
              />
              <p className="text-xs text-muted-foreground mt-1">
                Comma-separated entity type names.
              </p>
            </div>
            <div>
              <label className="text-xs font-medium mb-1 block text-muted-foreground">
                Properties (JSON)
              </label>
              <Input
                placeholder='{"since": "string", "role": "string"}'
                value={newRelationProperties}
                onChange={(e) => setNewRelationProperties(e.target.value)}
              />
            </div>
            <div>
              <label className="text-xs font-medium mb-1 block text-muted-foreground">
                Description
              </label>
              <Input
                placeholder="Optional description"
                value={newRelationDescription}
                onChange={(e) => setNewRelationDescription(e.target.value)}
              />
            </div>
            <div className="flex gap-2 pt-2">
              <Button onClick={handleCreateRelationType}>Create</Button>
              <Button variant="outline" onClick={() => setShowRelationForm(false)}>
                Cancel
              </Button>
            </div>
          </CardContent>
        </Card>
      )}

      <div className="mt-4 space-y-3">
        {loading ? (
          renderLoadingSkeleton(3)
        ) : relationTypes.length === 0 ? (
          renderEmptyState(
            <Share2 className="h-10 w-10 mb-3 opacity-30" />,
            'No relation types defined',
            'Create a relation type to define how entity types connect.',
          )
        ) : (
          relationTypes.map((rt) => {
            const parsed = parseRelationTypeContent(rt.content);
            const propCount = parsed.properties
              ? Object.keys(parsed.properties).length
              : 0;
            return (
              <div
                key={rt.id}
                className="rounded-lg border border-border p-4"
              >
                <div className="flex items-start justify-between">
                  <div className="min-w-0 flex-1 mr-3">
                    <h3 className="font-medium text-sm">{parsed.name}</h3>
                    <div className="flex items-center gap-2 mt-1.5 text-xs text-muted-foreground">
                      <span>
                        Source:{' '}
                        {parsed.sourceTypes.length > 0
                          ? parsed.sourceTypes.join(', ')
                          : '—'}
                      </span>
                      <span>→</span>
                      <span>
                        Target:{' '}
                        {parsed.targetTypes.length > 0
                          ? parsed.targetTypes.join(', ')
                          : '—'}
                      </span>
                    </div>
                    <div className="flex items-center gap-2 mt-1 text-xs text-muted-foreground">
                      {parsed.description && (
                        <span className="truncate max-w-[300px]">
                          {parsed.description}
                        </span>
                      )}
                      {propCount > 0 && (
                        <>
                          {parsed.description && <span>·</span>}
                          <span>{propCount} propert{propCount === 1 ? 'y' : 'ies'}</span>
                        </>
                      )}
                      <span>·</span>
                      <span>Created {formatMemoryTimestamp(rt.created_at)}</span>
                    </div>
                  </div>
                  <div className="flex items-center gap-1 shrink-0">
                    <Button
                      variant="ghost"
                      size="icon"
                      className="h-7 w-7 text-destructive hover:text-destructive"
                      onClick={() => handleDeleteRelationType(rt.id)}
                    >
                      <Trash2 className="h-3.5 w-3.5" />
                    </Button>
                  </div>
                </div>
              </div>
            );
          })
        )}
      </div>
    </TabsContent>
  );

  // -----------------------------------------------------------------------
  // Tab: Search Recipes
  // -----------------------------------------------------------------------

  const renderRecipesTab = () => (
    <TabsContent value="search-recipes">
      {!showRecipeForm && (
        <Button onClick={() => setShowRecipeForm(true)}>
          <Plus className="h-4 w-4 mr-1.5" />
          Create Search Recipe
        </Button>
      )}

      {showRecipeForm && (
        <Card>
          <CardHeader>
            <CardTitle className="text-lg">New Search Recipe</CardTitle>
          </CardHeader>
          <CardContent className="space-y-3">
            <div>
              <label className="text-xs font-medium mb-1 block text-muted-foreground">
                Name *
              </label>
              <Input
                placeholder="Find People by Name"
                value={newRecipeName}
                onChange={(e) => setNewRecipeName(e.target.value)}
              />
            </div>
            <div>
              <label className="text-xs font-medium mb-1 block text-muted-foreground">
                Query Template *
              </label>
              <Input
                placeholder="SELECT * FROM memory WHERE memory_type = 'person' AND content LIKE '%{query}%'"
                value={newRecipeQueryTemplate}
                onChange={(e) => setNewRecipeQueryTemplate(e.target.value)}
              />
              <p className="text-xs text-muted-foreground mt-1">
                Use {'{query}'} as a placeholder for runtime search terms.
              </p>
            </div>
            <div>
              <label className="text-xs font-medium mb-1 block text-muted-foreground">
                Filters (JSON)
              </label>
              <Input
                placeholder='{"memory_type": "person", "tier": "standard"}'
                value={newRecipeFilters}
                onChange={(e) => setNewRecipeFilters(e.target.value)}
              />
            </div>
            <div>
              <label className="text-xs font-medium mb-1 block text-muted-foreground">
                Description
              </label>
              <Input
                placeholder="Optional description"
                value={newRecipeDescription}
                onChange={(e) => setNewRecipeDescription(e.target.value)}
              />
            </div>
            <div className="flex gap-2 pt-2">
              <Button onClick={handleCreateRecipe}>Create</Button>
              <Button variant="outline" onClick={() => setShowRecipeForm(false)}>
                Cancel
              </Button>
            </div>
          </CardContent>
        </Card>
      )}

      <div className="mt-4 space-y-3">
        {loading ? (
          renderLoadingSkeleton(3)
        ) : recipes.length === 0 ? (
          renderEmptyState(
            <Search className="h-10 w-10 mb-3 opacity-30" />,
            'No search recipes defined',
            'Create a named search recipe to save and reuse search patterns.',
          )
        ) : (
          recipes.map((r) => {
            const parsed = parseRecipeContent(r.content);
            const filterCount = parsed.filters
              ? Object.keys(parsed.filters).length
              : 0;
            return (
              <div
                key={r.id}
                className="rounded-lg border border-border p-4"
              >
                <div className="flex items-start justify-between">
                  <div className="min-w-0 flex-1 mr-3">
                    <div className="flex items-center gap-2">
                      <h3 className="font-medium text-sm">{parsed.name}</h3>
                    </div>
                    <p className="text-xs text-muted-foreground mt-1 font-mono truncate max-w-lg">
                      {parsed.queryTemplate}
                    </p>
                    <div className="flex items-center gap-2 mt-1 text-xs text-muted-foreground">
                      {parsed.description && (
                        <span className="truncate max-w-[250px]">
                          {parsed.description}
                        </span>
                      )}
                      {filterCount > 0 && (
                        <>
                          {parsed.description && <span>·</span>}
                          <span>{filterCount} filter{filterCount !== 1 ? 's' : ''}</span>
                        </>
                      )}
                      <span>·</span>
                      <span>Created {formatMemoryTimestamp(r.created_at)}</span>
                    </div>
                  </div>
                  <div className="flex items-center gap-1 shrink-0">
                    <Button
                      variant="ghost"
                      size="icon"
                      className="h-7 w-7"
                      onClick={() => handleExecuteRecipe(r.id)}
                      title="Execute recipe"
                    >
                      <Play className="h-3.5 w-3.5" />
                    </Button>
                    <Button
                      variant="ghost"
                      size="icon"
                      className="h-7 w-7 text-destructive hover:text-destructive"
                      onClick={() => handleDeleteRecipe(r.id)}
                    >
                      <Trash2 className="h-3.5 w-3.5" />
                    </Button>
                  </div>
                </div>
              </div>
            );
          })
        )}
      </div>
    </TabsContent>
  );

  // -----------------------------------------------------------------------
  // Main render
  // -----------------------------------------------------------------------

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-3xl font-bold tracking-tight">Ontology</h1>
          <p className="text-muted-foreground">
            Manage entity types, relation types, and search recipes for the
            ontology system.
          </p>
        </div>
        <Button
          onClick={() => {
            if (activeTab === 'entity-types') loadEntityTypes();
            else if (activeTab === 'relation-types') loadRelationTypes();
            else loadRecipes();
          }}
          variant="ghost"
          size="icon"
        >
          <RefreshCw className="h-4 w-4" />
        </Button>
      </div>

      {renderError()}
      {renderSuccess()}

      <Tabs value={activeTab} onValueChange={setActiveTab}>
        <TabsList>
          <TabsTrigger value="entity-types">
            <Layers className="h-4 w-4 mr-1.5" />
            Entity Types
          </TabsTrigger>
          <TabsTrigger value="relation-types">
            <Share2 className="h-4 w-4 mr-1.5" />
            Relation Types
          </TabsTrigger>
          <TabsTrigger value="search-recipes">
            <Search className="h-4 w-4 mr-1.5" />
            Search Recipes
          </TabsTrigger>
        </TabsList>

        {renderEntityTypesTab()}
        {renderRelationTypesTab()}
        {renderRecipesTab()}
      </Tabs>
    </div>
  );
}
