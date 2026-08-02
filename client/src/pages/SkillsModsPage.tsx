import { useState, useCallback, useEffect } from 'react';
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { Tabs, TabsList, TabsTrigger, TabsContent } from '@/components/ui/tabs';
import {
  Puzzle,
  Package,
  Plus,
  Trash2,
  AlertCircle,
  RefreshCw,
  Check,
  X,
  Play,
  BookOpen,
  Terminal,
  Settings,
} from 'lucide-react';
import {
  callReducer,
  executeSql,
  parseSqlResponse,
  formatMemoryTimestamp,
} from '@/lib/spacetimedb';

interface MemoryRow {
  id: string;
  workspace_id: string;
  peer_id: string;
  observer_id: string;
  memory_type: string;
  content: string;
  summary: string;
  entities_json: string;
  confidence: number;
  source_session_id: string;
  source_message_id: string;
  is_active: boolean;
  created_at: string;
  expires_at: string;
  updated_at: string;
  tier: string;
  access_count: number;
  strength: number;
  version: number;
  valid_from: string;
  parent_directory_id: string;
  consolidated_to: string;
  trust_score: number;
  feedback_count: number;
}

interface SkillData {
  name: string;
  description: string;
  code: string;
  category: string;
  inputs: string[];
  outputs: string[];
}

interface ModData {
  name: string;
  version: string;
  config: Record<string, unknown>;
}

interface BuiltInSkill {
  name: string;
  description: string;
  category: string;
  code: string;
  inputs: string[];
  outputs: string[];
}

const BUILT_IN_SKILLS: BuiltInSkill[] = [
  {
    name: 'Summarize Text',
    description: 'Condenses long text passages into concise summaries with key points.',
    category: 'text-processing',
    code: 'summarize_text(input)',
    inputs: ['text: string'],
    outputs: ['summary: string'],
  },
  {
    name: 'Extract Entities',
    description: 'Identifies and extracts named entities (people, places, organizations) from text.',
    category: 'nlp',
    code: 'extract_entities(text)',
    inputs: ['text: string'],
    outputs: ['entities: array'],
  },
  {
    name: 'Sentiment Analysis',
    description: 'Analyzes the emotional tone of text and returns sentiment scores.',
    category: 'nlp',
    code: 'analyze_sentiment(text)',
    inputs: ['text: string'],
    outputs: ['sentiment: string', 'score: number'],
  },
  {
    name: 'Code Formatter',
    description: 'Formats source code according to language-specific style conventions.',
    category: 'developer-tools',
    code: 'format_code(code, language)',
    inputs: ['code: string', 'language: string'],
    outputs: ['formatted: string'],
  },
  {
    name: 'SQL Query Builder',
    description: 'Generates SQL queries from natural language descriptions.',
    category: 'developer-tools',
    code: 'build_sql(description)',
    inputs: ['description: string'],
    outputs: ['query: string'],
  },
  {
    name: 'Data Transformer',
    description: 'Transforms data between formats (JSON, CSV, YAML, XML).',
    category: 'data',
    code: 'transform_data(data, target_format)',
    inputs: ['data: string', 'target_format: string'],
    outputs: ['transformed: string'],
  },
  {
    name: 'Context Compressor',
    description: 'Compresses conversation history into a compact context summary.',
    category: 'memory',
    code: 'compress_context(messages, max_tokens)',
    inputs: ['messages: array', 'max_tokens: number'],
    outputs: ['context: string'],
  },
  {
    name: 'Memory Search',
    description: 'Searches across stored memories with semantic similarity matching.',
    category: 'memory',
    code: 'search_memories(query, limit)',
    inputs: ['query: string', 'limit: number'],
    outputs: ['results: array'],
  },
  {
    name: 'Prompt Optimizer',
    description: 'Rewrites prompts to improve clarity and effectiveness for LLM interactions.',
    category: 'llm',
    code: 'optimize_prompt(prompt)',
    inputs: ['prompt: string'],
    outputs: ['optimized: string', 'reasoning: string'],
  },
  {
    name: 'JSON Schema Validator',
    description: 'Validates JSON documents against a provided JSON Schema.',
    category: 'developer-tools',
    code: 'validate_json_schema(data, schema)',
    inputs: ['data: string', 'schema: string'],
    outputs: ['valid: boolean', 'errors: array'],
  },
];

export default function SkillsModsPage() {
  // Shared state
  const [skills, setSkills] = useState<MemoryRow[]>([]);
  const [mods, setMods] = useState<MemoryRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [successMsg, setSuccessMsg] = useState<string | null>(null);
  const [activeTab, setActiveTab] = useState('skills');

  // Skill create form state
  const [showSkillForm, setShowSkillForm] = useState(false);
  const [newSkillName, setNewSkillName] = useState('');
  const [newSkillDesc, setNewSkillDesc] = useState('');
  const [newSkillCode, setNewSkillCode] = useState('');
  const [newSkillCategory, setNewSkillCategory] = useState('');
  const [newSkillInputs, setNewSkillInputs] = useState('');
  const [newSkillOutputs, setNewSkillOutputs] = useState('');

  // Mod create form state
  const [showModForm, setShowModForm] = useState(false);
  const [newModName, setNewModName] = useState('');
  const [newModVersion, setNewModVersion] = useState('');
  const [newModConfig, setNewModConfig] = useState('{}');

  // Catalog expand state
  const [showCatalog, setShowCatalog] = useState(false);

  const clearMessages = () => {
    setError(null);
    setSuccessMsg(null);
  };

  const loadSkills = useCallback(async () => {

    setLoading(true);
    try {
      const res = await executeSql(
        "SELECT * FROM memory WHERE memory_type = 'skill' AND is_active = true ORDER BY created_at ASC"
      );
      const rows = parseSqlResponse<MemoryRow>(res);
      setSkills(rows);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load skills');
    } finally {
      setLoading(false);
    }
  }, []);

  const loadMods = useCallback(async () => {

    setLoading(true);
    try {
      const res = await executeSql(
        "SELECT * FROM memory WHERE memory_type = 'mod' AND is_active = true ORDER BY created_at ASC"
      );
      const rows = parseSqlResponse<MemoryRow>(res);
      setMods(rows);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load mods');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (activeTab === 'skills') {
      loadSkills();
    } else {
      loadMods();
    }
  }, [activeTab]);

  const handleCreateSkill = useCallback(async () => {
    clearMessages();
    if (!newSkillName.trim() || !newSkillDesc.trim() || !newSkillCode.trim()) {
      setError('Name, description, and code are required');
      return;
    }
    try {
      const skillData: SkillData = {
        name: newSkillName.trim(),
        description: newSkillDesc.trim(),
        code: newSkillCode.trim(),
        category: newSkillCategory.trim() || 'uncategorized',
        inputs: newSkillInputs.trim()
          ? newSkillInputs.split(',').map((s) => s.trim())
          : [],
        outputs: newSkillOutputs.trim()
          ? newSkillOutputs.split(',').map((s) => s.trim())
          : [],
      };
      await callReducer('store_memory', [
        '',
        '',
        '',
        'skill',
        JSON.stringify(skillData),
        skillData.description,
        '[]',
        1.0,
        '',
        '',
      ]);
      setSuccessMsg('Skill created successfully');
      setShowSkillForm(false);
      setNewSkillName('');
      setNewSkillDesc('');
      setNewSkillCode('');
      setNewSkillCategory('');
      setNewSkillInputs('');
      setNewSkillOutputs('');
      loadSkills();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to create skill');
    }
  }, [
    newSkillName,
    newSkillDesc,
    newSkillCode,
    newSkillCategory,
    newSkillInputs,
    newSkillOutputs,
    loadSkills,
  ]);

  const handleCreateMod = useCallback(async () => {
    clearMessages();
    if (!newModName.trim() || !newModVersion.trim()) {
      setError('Name and version are required');
      return;
    }
    let configParsed: Record<string, unknown> = {};
    try {
      configParsed = JSON.parse(newModConfig || '{}');
    } catch {
      setError('Config must be valid JSON');
      return;
    }
    try {
      const modData: ModData = {
        name: newModName.trim(),
        version: newModVersion.trim(),
        config: configParsed,
      };
      await callReducer('store_memory', [
        '',
        '',
        '',
        'mod',
        JSON.stringify(modData),
        `${modData.name} v${modData.version}`,
        '[]',
        1.0,
        '',
        '',
      ]);
      setSuccessMsg('Mod installed successfully');
      setShowModForm(false);
      setNewModName('');
      setNewModVersion('');
      setNewModConfig('{}');
      loadMods();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to install mod');
    }
  }, [newModName, newModVersion, newModConfig, loadMods]);

  const handleExecuteSkill = useCallback(
    async (skillId: string) => {
      clearMessages();
      try {
        await callReducer('execute_skill', [skillId]);
        setSuccessMsg('Skill executed');
      } catch (err) {
        setError(err instanceof Error ? err.message : 'Failed to execute skill');
      }
    },
    []
  );

  const handleDelete = useCallback(
    async (memoryId: string, type: 'skill' | 'mod') => {
      clearMessages();
      try {
        await callReducer('deactivate_memory', [memoryId]);
        setSuccessMsg(type === 'skill' ? 'Skill deleted' : 'Mod uninstalled');
        if (type === 'skill') {
          loadSkills();
        } else {
          loadMods();
        }
      } catch (err) {
        setError(
          err instanceof Error
            ? err.message
            : `Failed to delete ${type}`
        );
      }
    },
    [loadSkills, loadMods]
  );

  const parseSkillData = (mem: MemoryRow): SkillData => {
    try {
      return JSON.parse(mem.content) as SkillData;
    } catch {
      return {
        name: mem.summary || 'Unnamed Skill',
        description: '',
        code: '',
        category: 'uncategorized',
        inputs: [],
        outputs: [],
      };
    }
  };

  const parseModData = (mem: MemoryRow): ModData => {
    try {
      return JSON.parse(mem.content) as ModData;
    } catch {
      return {
        name: mem.summary || 'Unnamed Mod',
        version: '0.0.0',
        config: {},
      };
    }
  };

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-3xl font-bold tracking-tight">Skills &amp; Mods</h1>
          <p className="text-muted-foreground">
            Manage agent skills and installed modules (Letta parity).
          </p>
        </div>
        <Button
          onClick={activeTab === 'skills' ? loadSkills : loadMods}
          variant="ghost"
          size="icon"
        >
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
          <TabsTrigger value="skills">
            <Puzzle className="h-4 w-4 mr-1.5" />
            Skills
          </TabsTrigger>
          <TabsTrigger value="mods">
            <Package className="h-4 w-4 mr-1.5" />
            Mods
          </TabsTrigger>
        </TabsList>

        {/* ───────────────────── SKILLS TAB ───────────────────── */}
        <TabsContent value="skills">
          {/* Create skill button / form */}
          {!showSkillForm && (
            <div className="flex gap-2">
              <Button onClick={() => setShowSkillForm(true)}>
                <Plus className="h-4 w-4 mr-1.5" />
                Create Skill
              </Button>
              <Button variant="outline" onClick={() => setShowCatalog(!showCatalog)}>
                <BookOpen className="h-4 w-4 mr-1.5" />
                {showCatalog ? 'Hide Catalog' : 'Built-in Skills'}
              </Button>
            </div>
          )}

          {showSkillForm && (
            <Card>
              <CardHeader>
                <CardTitle className="text-lg">New Skill</CardTitle>
              </CardHeader>
              <CardContent className="space-y-3">
                <div>
                  <label className="text-xs font-medium mb-1 block text-muted-foreground">
                    Name *
                  </label>
                  <Input
                    placeholder="My Skill"
                    value={newSkillName}
                    onChange={(e) => setNewSkillName(e.target.value)}
                  />
                </div>
                <div>
                  <label className="text-xs font-medium mb-1 block text-muted-foreground">
                    Description *
                  </label>
                  <Input
                    placeholder="What this skill does"
                    value={newSkillDesc}
                    onChange={(e) => setNewSkillDesc(e.target.value)}
                  />
                </div>
                <div>
                  <label className="text-xs font-medium mb-1 block text-muted-foreground">
                    Code / Instructions *
                  </label>
                  <textarea
                    className="flex h-24 w-full rounded-md border border-input bg-background px-3 py-2 text-sm ring-offset-background placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-50"
                    placeholder="Skill code or instructions"
                    value={newSkillCode}
                    onChange={(e) => setNewSkillCode(e.target.value)}
                  />
                </div>
                <div className="grid grid-cols-3 gap-3">
                  <div>
                    <label className="text-xs font-medium mb-1 block text-muted-foreground">
                      Category
                    </label>
                    <Input
                      placeholder="text-processing"
                      value={newSkillCategory}
                      onChange={(e) => setNewSkillCategory(e.target.value)}
                    />
                  </div>
                  <div>
                    <label className="text-xs font-medium mb-1 block text-muted-foreground">
                      Inputs (comma-separated)
                    </label>
                    <Input
                      placeholder="text: string, lang: string"
                      value={newSkillInputs}
                      onChange={(e) => setNewSkillInputs(e.target.value)}
                    />
                  </div>
                  <div>
                    <label className="text-xs font-medium mb-1 block text-muted-foreground">
                      Outputs (comma-separated)
                    </label>
                    <Input
                      placeholder="summary: string"
                      value={newSkillOutputs}
                      onChange={(e) => setNewSkillOutputs(e.target.value)}
                    />
                  </div>
                </div>
                <div className="flex gap-2 pt-2">
                  <Button onClick={handleCreateSkill}>Create</Button>
                  <Button variant="outline" onClick={() => setShowSkillForm(false)}>
                    Cancel
                  </Button>
                </div>
              </CardContent>
            </Card>
          )}

          {/* Built-in skills catalog */}
          {showCatalog && (
            <div className="mt-4">
              <Card>
                <CardHeader>
                  <CardTitle className="text-lg flex items-center gap-2">
                    <BookOpen className="h-5 w-5" />
                    Built-in Skills Catalog
                  </CardTitle>
                  <CardDescription>
                    Reference cards for 10 pre-built skills. Click a card to copy the skill definition.
                  </CardDescription>
                </CardHeader>
                <CardContent>
                  <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
                    {BUILT_IN_SKILLS.map((sk) => (
                      <button
                        key={sk.name}
                        type="button"
                        className="text-left rounded-lg border border-border p-3 hover:border-primary/50 hover:bg-accent/30 transition-colors"
                        onClick={() => {
                          setNewSkillName(sk.name);
                          setNewSkillDesc(sk.description);
                          setNewSkillCode(sk.code);
                          setNewSkillCategory(sk.category);
                          setNewSkillInputs(sk.inputs.join(', '));
                          setNewSkillOutputs(sk.outputs.join(', '));
                          setShowSkillForm(true);
                          setShowCatalog(false);
                          setActiveTab('skills');
                        }}
                      >
                        <div className="flex items-center justify-between gap-2">
                          <h4 className="font-medium text-sm">{sk.name}</h4>
                          <Badge variant="secondary" className="text-xs shrink-0">
                            {sk.category}
                          </Badge>
                        </div>
                        <p className="text-xs text-muted-foreground mt-1 line-clamp-2">
                          {sk.description}
                        </p>
                        <div className="flex items-center gap-2 mt-2 text-[10px] text-muted-foreground">
                          <Terminal className="h-3 w-3" />
                          <code className="font-mono truncate">{sk.code}</code>
                        </div>
                        <div className="flex flex-wrap gap-1 mt-1.5">
                          {sk.inputs.map((inp) => (
                            <span
                              key={inp}
                              className="text-[10px] px-1.5 py-0.5 rounded bg-muted font-mono"
                            >
                              {inp}
                            </span>
                          ))}
                          <span className="text-[10px] text-muted-foreground">→</span>
                          {sk.outputs.map((out) => (
                            <span
                              key={out}
                              className="text-[10px] px-1.5 py-0.5 rounded bg-primary/10 font-mono"
                            >
                              {out}
                            </span>
                          ))}
                        </div>
                      </button>
                    ))}
                  </div>
                </CardContent>
              </Card>
            </div>
          )}

          {/* Skills list */}
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
            ) : skills.length === 0 ? (
              <div className="flex flex-col items-center justify-center py-12 text-muted-foreground">
                <Puzzle className="h-10 w-10 mb-3 opacity-30" />
                <p className="font-medium">No skills registered</p>
                <p className="text-sm mt-1">
                  Create a custom skill or browse the built-in catalog.
                </p>
              </div>
            ) : (
              skills.map((mem) => {
                const skill = parseSkillData(mem);
                return (
                  <div
                    key={mem.id}
                    className="rounded-lg border border-border p-4"
                  >
                    <div className="flex items-start justify-between">
                      <div className="min-w-0 flex-1 mr-3">
                        <div className="flex items-center gap-2">
                          <h3 className="font-medium text-sm">
                            {skill.name}
                          </h3>
                          <Badge variant="secondary" className="text-xs">
                            {skill.category}
                          </Badge>
                        </div>
                        <p className="text-xs text-muted-foreground mt-1 line-clamp-2">
                          {skill.description}
                        </p>
                        {(skill.inputs.length > 0 || skill.outputs.length > 0) && (
                          <div className="flex flex-wrap items-center gap-1 mt-1.5 text-xs">
                            {skill.inputs.length > 0 && (
                              <>
                                {skill.inputs.map((inp) => (
                                  <span
                                    key={inp}
                                    className="px-1.5 py-0.5 rounded bg-muted font-mono text-[10px]"
                                  >
                                    {inp}
                                  </span>
                                ))}
                                <span className="text-muted-foreground mx-0.5">→</span>
                              </>
                            )}
                            {skill.outputs.map((out) => (
                              <span
                                key={out}
                                className="px-1.5 py-0.5 rounded bg-primary/10 font-mono text-[10px]"
                              >
                                {out}
                              </span>
                            ))}
                          </div>
                        )}
                        {skill.code && (
                          <div className="mt-1.5">
                            <code className="text-[11px] font-mono text-muted-foreground bg-muted px-1.5 py-0.5 rounded">
                              {skill.code}
                            </code>
                          </div>
                        )}
                        <div className="flex items-center gap-2 mt-1.5 text-xs text-muted-foreground">
                          <span>
                            Created {formatMemoryTimestamp(mem.created_at)}
                          </span>
                          <span>·</span>
                          <span>Confidence: {mem.confidence.toFixed(1)}</span>
                        </div>
                      </div>
                      <div className="flex items-center gap-1 shrink-0">
                        <Button
                          variant="ghost"
                          size="icon"
                          className="h-7 w-7 text-green-600 hover:text-green-600"
                          onClick={() => handleExecuteSkill(mem.id)}
                          title="Execute skill"
                        >
                          <Play className="h-3.5 w-3.5" />
                        </Button>
                        <Button
                          variant="ghost"
                          size="icon"
                          className="h-7 w-7 text-destructive hover:text-destructive"
                          onClick={() => handleDelete(mem.id, 'skill')}
                          title="Delete skill"
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

        {/* ───────────────────── MODS TAB ───────────────────── */}
        <TabsContent value="mods">
          {/* Install mod button / form */}
          {!showModForm && (
            <Button onClick={() => setShowModForm(true)}>
              <Plus className="h-4 w-4 mr-1.5" />
              Install Mod
            </Button>
          )}

          {showModForm && (
            <Card>
              <CardHeader>
                <CardTitle className="text-lg">Install Mod</CardTitle>
              </CardHeader>
              <CardContent className="space-y-3">
                <div className="grid grid-cols-2 gap-3">
                  <div>
                    <label className="text-xs font-medium mb-1 block text-muted-foreground">
                      Name *
                    </label>
                    <Input
                      placeholder="my-agent-mod"
                      value={newModName}
                      onChange={(e) => setNewModName(e.target.value)}
                    />
                  </div>
                  <div>
                    <label className="text-xs font-medium mb-1 block text-muted-foreground">
                      Version *
                    </label>
                    <Input
                      placeholder="1.0.0"
                      value={newModVersion}
                      onChange={(e) => setNewModVersion(e.target.value)}
                    />
                  </div>
                </div>
                <div>
                  <label className="text-xs font-medium mb-1 block text-muted-foreground">
                    Config (JSON)
                  </label>
                  <textarea
                    className="flex h-24 w-full rounded-md border border-input bg-background px-3 py-2 text-sm font-mono ring-offset-background placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-50"
                    placeholder='{ "enabled": true, "settings": {} }'
                    value={newModConfig}
                    onChange={(e) => setNewModConfig(e.target.value)}
                  />
                  <p className="text-xs text-muted-foreground mt-1">
                    Optional configuration as a JSON object.
                  </p>
                </div>
                <div className="flex gap-2 pt-2">
                  <Button onClick={handleCreateMod}>Install</Button>
                  <Button variant="outline" onClick={() => setShowModForm(false)}>
                    Cancel
                  </Button>
                </div>
              </CardContent>
            </Card>
          )}

          {/* Mods list */}
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
                      <div className="h-3 w-32 rounded bg-muted animate-pulse" />
                    </div>
                    <div className="h-6 w-16 rounded-full bg-muted animate-pulse" />
                  </div>
                ))}
              </div>
            ) : mods.length === 0 ? (
              <div className="flex flex-col items-center justify-center py-12 text-muted-foreground">
                <Package className="h-10 w-10 mb-3 opacity-30" />
                <p className="font-medium">No mods installed</p>
                <p className="text-sm mt-1">
                  Install a mod to extend agent capabilities.
                </p>
              </div>
            ) : (
              mods.map((mem) => {
                const mod = parseModData(mem);
                const configKeys = Object.keys(mod.config);
                return (
                  <div
                    key={mem.id}
                    className="rounded-lg border border-border p-4"
                  >
                    <div className="flex items-start justify-between">
                      <div className="min-w-0 flex-1 mr-3">
                        <div className="flex items-center gap-2">
                          <h3 className="font-medium text-sm">{mod.name}</h3>
                          <Badge variant="outline" className="text-xs font-mono">
                            v{mod.version}
                          </Badge>
                          <Badge
                            variant={mem.is_active ? 'default' : 'secondary'}
                            className="text-xs"
                          >
                            {mem.is_active ? 'Active' : 'Inactive'}
                          </Badge>
                        </div>
                        {configKeys.length > 0 && (
                          <div className="mt-1.5 flex items-center gap-1">
                            <Settings className="h-3 w-3 text-muted-foreground" />
                            <span className="text-xs text-muted-foreground">
                              Config: {configKeys.join(', ')}
                            </span>
                          </div>
                        )}
                        <div className="flex items-center gap-2 mt-1.5 text-xs text-muted-foreground">
                          <span>
                            Installed {formatMemoryTimestamp(mem.created_at)}
                          </span>
                          <span>·</span>
                          <span>Strength: {mem.strength.toFixed(1)}</span>
                        </div>
                      </div>
                      <div className="flex items-center gap-1 shrink-0">
                        <Button
                          variant="ghost"
                          size="icon"
                          className="h-7 w-7 text-destructive hover:text-destructive"
                          onClick={() => handleDelete(mem.id, 'mod')}
                          title="Uninstall mod"
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
      </Tabs>
    </div>
  );
}
