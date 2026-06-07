import React, { useState, useMemo, useRef, useEffect } from 'react';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Tabs, TabsList, TabsTrigger, TabsContent } from '@/components/ui/tabs';
import { Skeleton } from '@/components/ui/skeleton';
import { useTable } from '@/lib/useReactiveDb';
import { formatMemoryTimestamp } from '@/lib/spacetimedb';
import { useLocation } from 'wouter';
import {
  BrainCircuit,
  MessageSquare,
  Clock,
  Users,
  Search,
  Download,
  StickyNote,
  AlertCircle,
  ChevronDown,
  ChevronRight,
  Lightbulb,
  Database,
  Network,
  Tags,
  User,
  Bot,
  FileText,
  Activity,
  X,
  Filter,
  CalendarDays,
  BookOpen,
  Award,
  BarChart3,
  RefreshCw,
} from 'lucide-react';

// ──────────────────────────────────────────────
// Types matching auto-generated SpacetimeDB bindings
// ──────────────────────────────────────────────

interface SessionRow {
  id: string;
  workspaceId: string;
  name: string;
  summary: string;
  metadata: string;
  createdAt: number;
  updatedAt: number;
}

interface MessageRow {
  id: string;
  sessionId: string;
  senderId: string;
  content: string;
  contentType: string;
  metadata: string;
  createdAt: number;
}

interface PeerRow {
  id: string;
  workspaceId: string;
  name: string;
  peerType: string;
  metadata: string;
  createdAt: number;
  updatedAt: number;
}

interface SessionParticipantRow {
  sessionId: string;
  peerId: string;
  role: string;
  joinedAt: number;
}

interface InsightRow {
  id: string;
  workspaceId: string;
  peerId: string;
  content: string;
  insightType: string;
  sourceMemoryIdsJson: string;
  confidence: number;
  createdAt: number;
}

interface MemoryRow {
  id: string;
  workspaceId: string;
  peerId: string;
  content: string;
  summary: string;
  sourceSessionId: string;
  isActive: boolean;
  createdAt: number;
  memoryType: string;
  [key: string]: unknown;
}

interface TagRow {
  id: string;
  workspaceId: string;
  name: string;
  color: string;
  createdAt: number;
}

interface KgNodeRow {
  id: string;
  workspaceId: string;
  label: string;
  nodeType: string;
  summary: string;
  createdAt: number;
}

// ──────────────────────────────────────────────
// Helpers
// ──────────────────────────────────────────────

function microsToDate(micros: number): Date {
  return new Date(micros / 1000);
}

function formatDuration(microsStart: number, microsEnd?: number): string {
  const start = microsToDate(microsStart).getTime();
  const end = microsEnd ? microsToDate(microsEnd).getTime() : Date.now();
  const diffMs = end - start;
  const secs = Math.floor(diffMs / 1000);
  if (secs < 60) return `${secs}s`;
  const mins = Math.floor(secs / 60);
  if (mins < 60) return `${mins}m ${secs % 60}s`;
  const hrs = Math.floor(mins / 60);
  return `${hrs}h ${mins % 60}m`;
}

function peerColor(peerType: string): string {
  switch (peerType?.toLowerCase()) {
    case 'user':
      return 'bg-blue-100 text-blue-800 border-blue-200 dark:bg-blue-900/30 dark:text-blue-300 dark:border-blue-800';
    case 'agent':
      return 'bg-green-100 text-green-800 border-green-200 dark:bg-green-900/30 dark:text-green-300 dark:border-green-800';
    case 'entity':
      return 'bg-gray-100 text-gray-700 border-gray-200 dark:bg-gray-800/50 dark:text-gray-300 dark:border-gray-700';
    default:
      return 'bg-purple-100 text-purple-800 border-purple-200 dark:bg-purple-900/30 dark:text-purple-300 dark:border-purple-800';
  }
}

function roleBadgeColor(role: string): string {
  switch (role?.toLowerCase()) {
    case 'user':
      return 'bg-blue-100 text-blue-700 dark:bg-blue-900/40 dark:text-blue-300';
    case 'assistant':
      return 'bg-green-100 text-green-700 dark:bg-green-900/40 dark:text-green-300';
    case 'tool_call':
      return 'bg-amber-100 text-amber-700 dark:bg-amber-900/40 dark:text-amber-300';
    case 'tool_result':
      return 'bg-purple-100 text-purple-700 dark:bg-purple-900/40 dark:text-purple-300';
    default:
      return 'bg-gray-100 text-gray-700 dark:bg-gray-800/50 dark:text-gray-300';
  }
}

function highlightTerms(text: string, terms: string[]): React.ReactNode {
  if (!terms.length || !text) return text;
  const escaped = terms.map((t) => t.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'));
  const re = new RegExp(`(${escaped.join('|')})`, 'gi');
  const parts = text.split(re);
  return parts.map((part, i) =>
    terms.some((t) => t.toLowerCase() === part.toLowerCase()) ? (
      <mark key={i} className="bg-yellow-200 dark:bg-yellow-800/50 rounded px-0.5">
        {part}
      </mark>
    ) : (
      part
    )
  );
}

// ──────────────────────────────────────────────
// Sub-components
// ──────────────────────────────────────────────

function LoadingSkeleton() {
  return (
    <div className="flex h-[calc(100vh-12rem)] gap-4">
      <div className="w-80 shrink-0 space-y-2">
        {Array.from({ length: 8 }).map((_, i) => (
          <div key={i} className="rounded-lg border border-border p-3 space-y-2">
            <Skeleton className="h-5 w-3/4" />
            <Skeleton className="h-3 w-1/2" />
            <Skeleton className="h-3 w-1/3" />
          </div>
        ))}
      </div>
      <div className="flex-1 rounded-lg border border-border p-6 space-y-4">
        <Skeleton className="h-8 w-1/3" />
        <Skeleton className="h-4 w-2/3" />
        <Skeleton className="h-40 w-full" />
        <Skeleton className="h-40 w-full" />
      </div>
    </div>
  );
}

function EmptyState({
  icon: Icon,
  title,
  description,
}: {
  icon: React.ElementType;
  title: string;
  description: string;
}) {
  return (
    <div className="flex flex-col items-center justify-center py-16 text-muted-foreground">
      <Icon className="h-12 w-12 mb-4 opacity-20" />
      <p className="text-lg font-medium">{title}</p>
      <p className="text-sm mt-1 max-w-md text-center">{description}</p>
    </div>
  );
}

function StatsCard({
  title,
  value,
  icon: Icon,
  color,
}: {
  title: string;
  value: string | number;
  icon: React.ElementType;
  color: string;
}) {
  return (
    <Card>
      <CardContent className="flex items-center gap-3 p-4">
        <div className={`rounded-lg p-2 ${color}`}>
          <Icon className="h-4 w-4" />
        </div>
        <div>
          <p className="text-xs text-muted-foreground">{title}</p>
          <p className="text-xl font-bold">{value}</p>
        </div>
      </CardContent>
    </Card>
  );
}

function SessionListItem({
  session,
  participants,
  messageCount,
  isSelected,
  onClick,
}: {
  session: SessionRow;
  participants: number;
  messageCount: number;
  isSelected: boolean;
  onClick: () => void;
}) {
  return (
    <button
      onClick={onClick}
      className={`w-full text-left rounded-lg border p-3 transition-colors hover:bg-accent/50 ${
        isSelected
          ? 'border-primary bg-accent/30 ring-1 ring-primary'
          : 'border-border'
      }`}
    >
      <div className="flex items-start gap-2">
        <MessageSquare className="mt-0.5 h-4 w-4 shrink-0 text-muted-foreground" />
        <div className="min-w-0 flex-1">
          <p className="font-medium text-sm truncate">
            {session.name || session.id.slice(0, 24) + '…'}
          </p>
          <div className="flex items-center gap-2 text-xs text-muted-foreground mt-1">
            <Clock className="h-3 w-3" />
            <span>{formatMemoryTimestamp(session.createdAt)}</span>
          </div>
          <div className="flex items-center gap-3 text-xs text-muted-foreground mt-1">
            <span className="flex items-center gap-1">
              <Users className="h-3 w-3" />
              {participants}
            </span>
            <span className="flex items-center gap-1">
              <MessageSquare className="h-3 w-3" />
              {messageCount}
            </span>
          </div>
          {session.summary && (
            <p className="text-xs text-muted-foreground mt-1.5 line-clamp-2">
              {session.summary}
            </p>
          )}
        </div>
      </div>
    </button>
  );
}

function MessageBubble({
  message,
  peers,
  searchHighlight,
}: {
  message: MessageRow;
  peers: Map<string, PeerRow>;
  searchHighlight?: string;
}) {
  const [collapsed, setCollapsed] = useState(true);
  const isToolCall = message.contentType === 'tool_call' || message.contentType === 'tool_result';
  const peer = peers.get(message.senderId);

  let roleDisplay = message.contentType || 'unknown';
  let displayContent = message.content;

  // For tool calls, try to parse JSON for better display
  let parsedTool: { name?: string; args?: unknown; result?: unknown } | null = null;
  if (isToolCall) {
    try {
      const parsed = JSON.parse(message.content);
      if (typeof parsed === 'object') {
        parsedTool = parsed;
        if (parsed.name) {
          roleDisplay = `tool_call: ${parsed.name}`;
        }
        if (parsed.result !== undefined) {
          displayContent = typeof parsed.result === 'string' ? parsed.result : JSON.stringify(parsed.result, null, 2);
        } else if (parsed.args) {
          displayContent = JSON.stringify(parsed.args, null, 2);
        }
      }
    } catch {
      // not JSON, use as-is
    }
  }

  return (
    <div
      className={`flex flex-col gap-1 ${
        message.contentType === 'user' ? 'items-end' : 'items-start'
      }`}
    >
      <div
        className={`max-w-[80%] rounded-lg px-3 py-2 text-sm ${
          message.contentType === 'user'
            ? 'bg-primary text-primary-foreground'
            : isToolCall
            ? 'bg-muted/50 border border-border'
            : 'bg-muted'
        }`}
      >
        {/* Header */}
        <div className="flex items-center gap-2 mb-1">
          <Badge
            variant="outline"
            className={`text-[10px] px-1.5 py-0 font-mono ${roleBadgeColor(message.contentType)}`}
          >
            {roleDisplay}
          </Badge>
          {peer && (
            <span className="text-[10px] text-muted-foreground">{peer.name}</span>
          )}
          <span className="text-[10px] text-muted-foreground ml-auto">
            {formatMemoryTimestamp(message.createdAt)}
          </span>
        </div>

        {/* Content */}
        {isToolCall ? (
          <div>
            <button
              onClick={() => setCollapsed(!collapsed)}
              className="flex items-center gap-1 text-xs font-medium text-muted-foreground hover:text-foreground transition-colors"
            >
              {collapsed ? (
                <ChevronRight className="h-3 w-3" />
              ) : (
                <ChevronDown className="h-3 w-3" />
              )}
              {parsedTool?.name
                ? `Call: ${parsedTool.name}`
                : message.contentType === 'tool_call'
                ? 'Tool Call'
                : 'Tool Result'}
            </button>
            {!collapsed && (
              <pre className="mt-1 text-xs overflow-x-auto whitespace-pre-wrap font-mono bg-background/50 rounded p-2 max-h-48 overflow-y-auto">
                {searchHighlight
                  ? highlightTerms(displayContent, [searchHighlight])
                  : displayContent}
              </pre>
            )}
          </div>
        ) : (
          <div className="text-sm whitespace-pre-wrap break-words">
            {searchHighlight
              ? highlightTerms(message.content, [searchHighlight])
              : message.content}
          </div>
        )}
      </div>
    </div>
  );
}

function ParticipantBadge({ peer, peerType }: { peer: PeerRow; peerType?: string }) {
  const Icon = peer.peerType === 'user' ? User : peer.peerType === 'agent' ? Bot : Users;
  const type = peerType || peer.peerType || 'unknown';
  return (
    <Badge
      variant="outline"
      className={`inline-flex items-center gap-1 ${peerColor(peer.peerType)}`}
    >
      <Icon className="h-3 w-3" />
      <span>{peer.name || peer.id.slice(0, 12)}</span>
      <span className="text-[10px] opacity-70">({type})</span>
    </Badge>
  );
}

// ──────────────────────────────────────────────
// Main component
// ──────────────────────────────────────────────

export default function SessionReasoning() {
  const [, setLocation] = useLocation();

  // Reactive data
  const { data: sessionsAll, loading, error } = useTable<SessionRow>('session');
  const { data: messages } = useTable<MessageRow>('message');
  const { data: peers } = useTable<PeerRow>('peer');
  const { data: participants } = useTable<SessionParticipantRow>('session_participant');
  const { data: insights } = useTable<InsightRow>('insight');
  const { data: memories } = useTable<MemoryRow>('memory');
  const { data: tags } = useTable<TagRow>('tag');
  const { data: kgNodes } = useTable<KgNodeRow>('kg_node');

  // Local state
  const [selectedSessionId, setSelectedSessionId] = useState<string | null>(null);
  const [sessionSearch, setSessionSearch] = useState('');
  const [messageSearch, setMessageSearch] = useState('');
  const [activeTab, setActiveTab] = useState('messages');
  const [dateFilterStart, setDateFilterStart] = useState('');
  const [dateFilterEnd, setDateFilterEnd] = useState('');
  const [participantFilter, setParticipantFilter] = useState<string>('');
  const [showFilters, setShowFilters] = useState(false);
  const messagesEndRef = useRef<HTMLDivElement>(null);

  // Build lookup maps
  const peerMap = useMemo(() => {
    const map = new Map<string, PeerRow>();
    for (const p of peers) map.set(p.id, p);
    return map;
  }, [peers]);

  const sessionsByPeer = useMemo(() => {
    const map = new Map<string, Set<string>>();
    for (const p of participants) {
      if (!map.has(p.peerId)) map.set(p.peerId, new Set());
      map.get(p.peerId)!.add(p.sessionId);
    }
    // Also check messages for participants not in session_participant
    for (const m of messages) {
      if (!map.has(m.senderId)) map.set(m.senderId, new Set());
      map.get(m.senderId)!.add(m.sessionId);
    }
    return map;
  }, [participants, messages]);

  // Compute message counts per session
  const messageCountBySession = useMemo(() => {
    const map = new Map<string, number>();
    for (const m of messages) {
      map.set(m.sessionId, (map.get(m.sessionId) || 0) + 1);
    }
    return map;
  }, [messages]);

  // Compute participant counts per session
  const participantCountBySession = useMemo(() => {
    const map = new Map<string, Set<string>>();
    for (const p of participants) {
      if (!map.has(p.sessionId)) map.set(p.sessionId, new Set());
      map.get(p.sessionId)!.add(p.peerId);
    }
    // Also count message senders
    for (const m of messages) {
      if (!map.has(m.sessionId)) map.set(m.sessionId, new Set());
      map.get(m.sessionId)!.add(m.senderId);
    }
    const countMap = new Map<string, number>();
    for (const [sid, pset] of map) countMap.set(sid, pset.size);
    return countMap;
  }, [participants, messages]);

  // Filter & sort sessions
  const sessions = useMemo(() => {
    let filtered = [...sessionsAll];

    // Search by name
    if (sessionSearch) {
      const q = sessionSearch.toLowerCase();
      filtered = filtered.filter(
        (s) =>
          s.name?.toLowerCase().includes(q) ||
          s.summary?.toLowerCase().includes(q) ||
          s.id.toLowerCase().includes(q)
      );
    }

    // Date filter
    if (dateFilterStart) {
      const startMs = new Date(dateFilterStart).getTime() * 1000;
      filtered = filtered.filter((s) => s.createdAt >= startMs);
    }
    if (dateFilterEnd) {
      const endMs = new Date(dateFilterEnd).getTime() * 1000;
      filtered = filtered.filter((s) => s.createdAt <= endMs);
    }

    // Participant filter
    if (participantFilter && sessionsByPeer.has(participantFilter)) {
      const sessionIds = sessionsByPeer.get(participantFilter)!;
      filtered = filtered.filter((s) => sessionIds.has(s.id));
    }

    // Sort newest first
    filtered.sort((a, b) => b.createdAt - a.createdAt);
    return filtered;
  }, [sessionsAll, sessionSearch, dateFilterStart, dateFilterEnd, participantFilter, sessionsByPeer]);

  const selectedSession = useMemo(
    () => sessionsAll.find((s) => s.id === selectedSessionId) ?? null,
    [sessionsAll, selectedSessionId]
  );

  const selectedMessages = useMemo(() => {
    if (!selectedSessionId) return [];
    const msgs = messages
      .filter((m) => m.sessionId === selectedSessionId)
      .sort((a, b) => a.createdAt - b.createdAt);

    if (messageSearch) {
      const q = messageSearch.toLowerCase();
      return msgs.filter(
        (m) =>
          m.content?.toLowerCase().includes(q) ||
          m.contentType?.toLowerCase().includes(q)
      );
    }
    return msgs;
  }, [messages, selectedSessionId, messageSearch]);

  const selectedParticipants = useMemo(() => {
    if (!selectedSessionId) return [];
    const peerIds = new Set<string>();

    // From session_participant table
    for (const p of participants) {
      if (p.sessionId === selectedSessionId) peerIds.add(p.peerId);
    }
    // Also from messages
    for (const m of messages) {
      if (m.sessionId === selectedSessionId) peerIds.add(m.senderId);
    }

    return Array.from(peerIds)
      .map((pid) => peerMap.get(pid))
      .filter((p): p is PeerRow => !!p);
  }, [selectedSessionId, participants, messages, peerMap]);

  const selectedInsights = useMemo(() => {
    if (!selectedSession) return [];
    // Insights linked to this session's peers
    return insights.filter((i) => {
      const peerIds = new Set(selectedParticipants.map((p) => p.id));
      return peerIds.has(i.peerId);
    });
  }, [insights, selectedSession, selectedParticipants]);

  const selectedMemories = useMemo(() => {
    if (!selectedSessionId) return [];
    return memories.filter(
      (m) => m.sourceSessionId === selectedSessionId && m.isActive
    );
  }, [memories, selectedSessionId]);

  // Auto-scroll messages to bottom
  useEffect(() => {
    if (activeTab === 'messages' && messagesEndRef.current) {
      messagesEndRef.current.scrollIntoView({ behavior: 'smooth' });
    }
  }, [selectedMessages, activeTab]);

  // Compute stats
  const stats = useMemo(() => {
    const total = sessionsAll.length;
    const active = sessionsAll.filter(
      (s) => s.updatedAt > Date.now() * 1000 - 3600_000_000
    ).length; // active in last hour
    const totalMessages = messages.length;
    const avgMessages = total > 0 ? Math.round(totalMessages / total) : 0;
    return { total, active, totalMessages, avgMessages };
  }, [sessionsAll, messages]);

  // ─── Actions ──────────────────────────────

  function handleExportSession() {
    if (!selectedSession) return;
    const data = {
      session: {
        id: selectedSession.id,
        name: selectedSession.name,
        summary: selectedSession.summary,
        createdAt: selectedSession.createdAt,
      },
      messages: selectedMessages.map((m) => ({
        role: m.contentType,
        content: m.content,
        sender: m.senderId,
        timestamp: m.createdAt,
      })),
    };
    const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `session-${selectedSession.id.slice(0, 8)}.json`;
    a.click();
    URL.revokeObjectURL(url);
  }

  function handleCreateNote() {
    if (!selectedSession) return;
    setLocation(`/notes/new?session=${selectedSession.id}`);
  }

  function handleReactivate() {
    // This would call a reducer — for now we just show a UI action
    // callReducer('update_session_summary', [selectedSession!.id, selectedSession!.summary])
    // For now it's a placeholder action
    alert('Re-activate would call update_session reducer. (Placeholder)');
  }

  // ─── Render ──────────────────────────────

  if (error) {
    return (
      <div className="space-y-6">
        <div>
          <h1 className="text-3xl font-bold tracking-tight">Session Reasoning</h1>
        </div>
        <Card>
          <CardContent className="flex items-center gap-3 py-6 text-destructive">
            <AlertCircle className="h-5 w-5" />
            <p className="text-sm">{error}</p>
          </CardContent>
        </Card>
      </div>
    );
  }

  return (
    <div className="space-y-4">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-3xl font-bold tracking-tight">Session Reasoning</h1>
          <p className="text-muted-foreground text-sm">
            {loading
              ? 'Loading sessions...'
              : `${sessionsAll.length} session${sessionsAll.length !== 1 ? 's' : ''}`}
          </p>
        </div>
        <div className="flex items-center gap-2">
          <BrainCircuit className="h-6 w-6 text-primary opacity-60" />
        </div>
      </div>

      {/* Stats bar */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        <StatsCard
          title="Total Sessions"
          value={loading ? '…' : stats.total}
          icon={Activity}
          color="bg-blue-100 text-blue-600 dark:bg-blue-900/30 dark:text-blue-400"
        />
        <StatsCard
          title="Active (1h)"
          value={loading ? '…' : stats.active}
          icon={BarChart3}
          color="bg-green-100 text-green-600 dark:bg-green-900/30 dark:text-green-400"
        />
        <StatsCard
          title="Total Messages"
          value={loading ? '…' : stats.totalMessages}
          icon={MessageSquare}
          color="bg-purple-100 text-purple-600 dark:bg-purple-900/30 dark:text-purple-400"
        />
        <StatsCard
          title="Avg / Session"
          value={loading ? '…' : stats.avgMessages}
          icon={BarChart3}
          color="bg-amber-100 text-amber-600 dark:bg-amber-900/30 dark:text-amber-400"
        />
      </div>

      {/* Main layout: session list + detail */}
      {loading ? (
        <LoadingSkeleton />
      ) : sessionsAll.length === 0 ? (
        <EmptyState
          icon={MessageSquare}
          title="No sessions yet"
          description="Start interacting to create sessions. Sessions appear here once agents or users engage in conversation."
        />
      ) : (
        <div className="flex h-[calc(100vh-18rem)] gap-4">
          {/* ─── Left panel: session list ─── */}
          <div className="w-80 shrink-0 flex flex-col border border-border rounded-lg bg-card overflow-hidden">
            {/* Search */}
            <div className="p-3 border-b border-border space-y-2">
              <div className="relative">
                <Search className="absolute left-2.5 top-2.5 h-4 w-4 text-muted-foreground" />
                <Input
                  placeholder="Search sessions..."
                  value={sessionSearch}
                  onChange={(e) => setSessionSearch(e.target.value)}
                  className="pl-8 h-9 text-sm"
                />
              </div>
              <Button
                variant="ghost"
                size="sm"
                onClick={() => setShowFilters(!showFilters)}
                className="flex items-center gap-1 text-xs w-full justify-start"
              >
                <Filter className="h-3 w-3" />
                Filters
                {showFilters ? (
                  <ChevronDown className="h-3 w-3 ml-auto" />
                ) : (
                  <ChevronRight className="h-3 w-3 ml-auto" />
                )}
              </Button>
              {showFilters && (
                <div className="space-y-2 pt-1">
                  <div className="flex items-center gap-2">
                    <CalendarDays className="h-3 w-3 text-muted-foreground shrink-0" />
                    <input
                      type="date"
                      value={dateFilterStart}
                      onChange={(e) => setDateFilterStart(e.target.value)}
                      className="text-xs bg-transparent border border-border rounded px-2 py-1 w-full"
                      placeholder="From"
                    />
                    <span className="text-xs text-muted-foreground">-</span>
                    <input
                      type="date"
                      value={dateFilterEnd}
                      onChange={(e) => setDateFilterEnd(e.target.value)}
                      className="text-xs bg-transparent border border-border rounded px-2 py-1 w-full"
                      placeholder="To"
                    />
                  </div>
                  <div>
                    <select
                      value={participantFilter}
                      onChange={(e) => setParticipantFilter(e.target.value)}
                      className="text-xs bg-transparent border border-border rounded px-2 py-1 w-full"
                    >
                      <option value="">All participants</option>
                      {peers.map((p) => (
                        <option key={p.id} value={p.id}>
                          {p.name || p.id.slice(0, 12)}
                        </option>
                      ))}
                    </select>
                  </div>
                  {(dateFilterStart || dateFilterEnd || participantFilter) && (
                    <Button
                      variant="ghost"
                      size="sm"
                      onClick={() => {
                        setDateFilterStart('');
                        setDateFilterEnd('');
                        setParticipantFilter('');
                      }}
                      className="text-xs h-7 w-full"
                    >
                      <X className="h-3 w-3 mr-1" />
                      Clear filters
                    </Button>
                  )}
                </div>
              )}
            </div>

            {/* Session list */}
            <div className="flex-1 overflow-y-auto p-3 space-y-2">
              {sessions.length === 0 ? (
                <div className="text-center py-8 text-muted-foreground text-sm">
                  No sessions match your search.
                </div>
              ) : (
                sessions.map((session) => (
                  <SessionListItem
                    key={session.id}
                    session={session}
                    participants={participantCountBySession.get(session.id) || 0}
                    messageCount={messageCountBySession.get(session.id) || 0}
                    isSelected={session.id === selectedSessionId}
                    onClick={() => setSelectedSessionId(session.id)}
                  />
                ))
              )}
            </div>

            {/* Session count */}
            <div className="border-t border-border p-2 text-center text-xs text-muted-foreground">
              {sessions.length} / {sessionsAll.length} sessions
            </div>
          </div>

          {/* ─── Right panel: session detail ─── */}
          <div className="flex-1 border border-border rounded-lg bg-card overflow-hidden flex flex-col">
            {!selectedSession ? (
              <div className="flex-1 flex items-center justify-center">
                <EmptyState
                  icon={BrainCircuit}
                  title="Select a session"
                  description="Choose a session from the left panel to view its reasoning context, messages, and insights."
                />
              </div>
            ) : selectedMessages.length === 0 && !selectedSession.summary ? (
              <div className="flex-1 flex flex-col">
                {/* Header */}
                <div className="p-4 border-b border-border">
                  <SessionDetailHeader
                    session={selectedSession}
                    participants={selectedParticipants}
                    duration={formatDuration(selectedSession.createdAt, selectedSession.updatedAt || undefined)}
                  />
                  <SessionActions
                    onExport={handleExportSession}
                    onCreateNote={handleCreateNote}
                    onReactivate={handleReactivate}
                  />
                </div>
                <div className="flex-1 flex items-center justify-center">
                  <EmptyState
                    icon={MessageSquare}
                    title="This session has no messages"
                    description="Messages will appear here once the conversation starts."
                  />
                </div>
              </div>
            ) : (
              <>
                {/* Session header */}
                <div className="p-4 border-b border-border shrink-0">
                  <SessionDetailHeader
                    session={selectedSession}
                    participants={selectedParticipants}
                    duration={formatDuration(selectedSession.createdAt, selectedSession.updatedAt || undefined)}
                  />
                  <SessionActions
                    onExport={handleExportSession}
                    onCreateNote={handleCreateNote}
                    onReactivate={handleReactivate}
                  />
                </div>

                {/* Tabs */}
                <Tabs
                  defaultValue="messages"
                  value={activeTab}
                  onValueChange={setActiveTab}
                  className="flex-1 flex flex-col overflow-hidden"
                >
                  <div className="px-4 pt-2 border-b border-border shrink-0">
                    <TabsList>
                      <TabsTrigger value="messages" className="text-xs gap-1">
                        <MessageSquare className="h-3.5 w-3.5" />
                        Messages
                        <span className="ml-1 text-[10px] text-muted-foreground">
                          ({selectedMessages.length})
                        </span>
                      </TabsTrigger>
                      <TabsTrigger value="context" className="text-xs gap-1">
                        <BookOpen className="h-3.5 w-3.5" />
                        Context
                      </TabsTrigger>
                      <TabsTrigger value="insights" className="text-xs gap-1">
                        <Lightbulb className="h-3.5 w-3.5" />
                        Insights
                        <span className="ml-1 text-[10px] text-muted-foreground">
                          ({selectedInsights.length})
                        </span>
                      </TabsTrigger>
                    </TabsList>
                  </div>

                  {/* ─── Messages tab ─── */}
                  <TabsContent value="messages" className="flex-1 flex flex-col overflow-hidden m-0 p-0">
                    {/* Message search */}
                    <div className="px-4 py-2 border-b border-border shrink-0">
                      <div className="relative">
                        <Search className="absolute left-2.5 top-2.5 h-4 w-4 text-muted-foreground" />
                        <Input
                          placeholder="Search messages..."
                          value={messageSearch}
                          onChange={(e) => setMessageSearch(e.target.value)}
                          className="pl-8 h-8 text-sm"
                        />
                      </div>
                    </div>

                    {/* Message list */}
                    <div className="flex-1 overflow-y-auto p-4 space-y-3">
                      {selectedMessages.length === 0 ? (
                        <div className="text-center py-8 text-muted-foreground text-sm">
                          {messageSearch
                            ? 'No messages match your search.'
                            : 'This session has no messages.'}
                        </div>
                      ) : (
                        selectedMessages.map((msg) => (
                          <MessageBubble
                            key={msg.id}
                            message={msg}
                            peers={peerMap}
                            searchHighlight={messageSearch || undefined}
                          />
                        ))
                      )}
                      <div ref={messagesEndRef} />
                    </div>
                  </TabsContent>

                  {/* ─── Context tab ─── */}
                  <TabsContent value="context" className="flex-1 overflow-y-auto p-4">
                    <div className="space-y-4">
                      {/* Session Context / Goal */}
                      <Card>
                        <CardHeader className="pb-2">
                          <CardTitle className="text-sm flex items-center gap-2">
                            <BookOpen className="h-4 w-4 text-primary" />
                            Session Context
                          </CardTitle>
                        </CardHeader>
                        <CardContent>
                          {selectedSession.summary ? (
                            <p className="text-sm text-foreground whitespace-pre-wrap">
                              {selectedSession.summary}
                            </p>
                          ) : (
                            <p className="text-sm text-muted-foreground italic">
                              No context summary recorded for this session.
                            </p>
                          )}
                        </CardContent>
                      </Card>

                      {/* Extracted Entities */}
                      <Card>
                        <CardHeader className="pb-2">
                          <CardTitle className="text-sm flex items-center gap-2">
                            <Network className="h-4 w-4 text-primary" />
                            Extracted Entities
                          </CardTitle>
                        </CardHeader>
                        <CardContent>
                          {(() => {
                            // Extract potential entities from message content
                            const entityCandidates = new Map<string, number>();
                            const wordPattern = /\b[A-Z][a-z]+(?:\s[A-Z][a-z]+)*\b/g;

                            for (const msg of selectedMessages) {
                              const words = msg.content.match(wordPattern) || [];
                              for (const w of words) {
                                if (w.length > 2) {
                                  entityCandidates.set(
                                    w,
                                    (entityCandidates.get(w) || 0) + 1
                                  );
                                }
                              }
                            }

                            const sorted = Array.from(entityCandidates.entries())
                              .sort((a, b) => b[1] - a[1])
                              .slice(0, 30);

                            if (sorted.length === 0) {
                              return (
                                <p className="text-sm text-muted-foreground italic">
                                  No entities extracted yet.
                                </p>
                              );
                            }

                            return (
                              <div className="flex flex-wrap gap-1.5">
                                {sorted.map(([entity, count]) => (
                                  <Badge
                                    key={entity}
                                    variant="outline"
                                    className="text-xs"
                                  >
                                    {entity}
                                    <span className="ml-1 text-[10px] text-muted-foreground">
                                      ×{count}
                                    </span>
                                  </Badge>
                                ))}
                              </div>
                            );
                          })()}
                        </CardContent>
                      </Card>

                      {/* Session Tags / Topics */}
                      <Card>
                        <CardHeader className="pb-2">
                          <CardTitle className="text-sm flex items-center gap-2">
                            <Tags className="h-4 w-4 text-primary" />
                            Tags & Topics
                          </CardTitle>
                        </CardHeader>
                        <CardContent>
                          {tags.length === 0 ? (
                            <p className="text-sm text-muted-foreground italic">
                              No tags defined yet.
                            </p>
                          ) : (
                            <div className="flex flex-wrap gap-1.5">
                              {tags.map((tag) => (
                                <Badge
                                  key={tag.id}
                                  className="text-xs"
                                  style={{
                                    backgroundColor: tag.color
                                      ? `${tag.color}20`
                                      : undefined,
                                    borderColor: tag.color || undefined,
                                    color: tag.color || undefined,
                                  }}
                                >
                                  {tag.name}
                                </Badge>
                              ))}
                            </div>
                          )}
                        </CardContent>
                      </Card>

                      {/* Session Summary (placeholder) */}
                      <Card className="border-dashed">
                        <CardHeader className="pb-2">
                          <CardTitle className="text-sm flex items-center gap-2">
                            <Award className="h-4 w-4 text-amber-500" />
                            Session Summary
                            <Badge
                              variant="outline"
                              className="text-[10px] text-muted-foreground ml-auto"
                            >
                              LLM-generated
                            </Badge>
                          </CardTitle>
                        </CardHeader>
                        <CardContent>
                          <p className="text-sm text-muted-foreground italic">
                            Session summaries are generated by the LLM during
                            consolidation. Run consolidation or check back after
                            the session is complete.
                          </p>
                          {selectedMemories.length > 0 && (
                            <div className="mt-3">
                              <p className="text-xs font-medium text-muted-foreground mb-2">
                                Memories created during this session:
                              </p>
                              <div className="space-y-1">
                                {selectedMemories.slice(0, 5).map((mem) => (
                                  <div
                                    key={mem.id}
                                    className="text-xs text-muted-foreground border-l-2 border-primary/30 pl-2 py-0.5"
                                  >
                                    {mem.summary || mem.content?.slice(0, 100)}
                                  </div>
                                ))}
                                {selectedMemories.length > 5 && (
                                  <p className="text-xs text-muted-foreground mt-1">
                                    +{selectedMemories.length - 5} more memories
                                  </p>
                                )}
                              </div>
                            </div>
                          )}
                        </CardContent>
                      </Card>
                    </div>
                  </TabsContent>

                  {/* ─── Insights tab ─── */}
                  <TabsContent value="insights" className="flex-1 overflow-y-auto p-4">
                    <div className="space-y-4">
                      {/* Key Decisions */}
                      <Card>
                        <CardHeader className="pb-2">
                          <CardTitle className="text-sm flex items-center gap-2">
                            <Lightbulb className="h-4 w-4 text-amber-500" />
                            Key Decisions
                          </CardTitle>
                        </CardHeader>
                        <CardContent>
                          {selectedInsights.length === 0 ? (
                            <p className="text-sm text-muted-foreground italic">
                              No decisions or insights recorded for this session.
                            </p>
                          ) : (
                            <div className="space-y-2">
                              {selectedInsights.map((insight) => (
                                <div
                                  key={insight.id}
                                  className="border border-border rounded-lg p-3"
                                >
                                  <div className="flex items-center gap-2 mb-1">
                                    <Badge
                                      variant="outline"
                                      className="text-[10px]"
                                    >
                                      {insight.insightType || 'insight'}
                                    </Badge>
                                    <span className="text-[10px] text-muted-foreground">
                                      {formatMemoryTimestamp(insight.createdAt)}
                                    </span>
                                    {peerMap.has(insight.peerId) && (
                                      <span className="text-[10px] text-muted-foreground ml-auto">
                                        by {peerMap.get(insight.peerId)!.name}
                                      </span>
                                    )}
                                  </div>
                                  <p className="text-sm">{insight.content}</p>
                                  <div className="flex items-center gap-2 mt-1">
                                    <span className="text-[10px] text-muted-foreground">
                                      Confidence:{' '}
                                      {(insight.confidence * 100).toFixed(0)}%
                                    </span>
                                  </div>
                                </div>
                              ))}
                            </div>
                          )}
                        </CardContent>
                      </Card>

                      {/* Memories Created */}
                      <Card>
                        <CardHeader className="pb-2">
                          <CardTitle className="text-sm flex items-center gap-2">
                            <Database className="h-4 w-4 text-blue-500" />
                            Memories Created
                          </CardTitle>
                        </CardHeader>
                        <CardContent>
                          {selectedMemories.length === 0 ? (
                            <p className="text-sm text-muted-foreground italic">
                              No memories created during this session.
                            </p>
                          ) : (
                            <div className="space-y-2">
                              {selectedMemories.slice(0, 10).map((mem) => (
                                <div
                                  key={mem.id}
                                  className="border border-border rounded-lg p-3"
                                >
                                  <div className="flex items-center gap-2 mb-1">
                                    <Badge
                                      variant="outline"
                                      className="text-[10px]"
                                    >
                                      {mem.memoryType || 'memory'}
                                    </Badge>
                                    <span className="text-[10px] text-muted-foreground">
                                      {formatMemoryTimestamp(mem.createdAt)}
                                    </span>
                                    {peerMap.has(mem.peerId) && (
                                      <span className="text-[10px] text-muted-foreground ml-auto">
                                        by {peerMap.get(mem.peerId)!.name}
                                      </span>
                                    )}
                                  </div>
                                  <p className="text-sm">
                                    {mem.summary || mem.content?.slice(0, 200)}
                                  </p>
                                  {mem.content && mem.content.length > 200 && (
                                    <span className="text-[10px] text-muted-foreground">
                                      ...
                                    </span>
                                  )}
                                </div>
                              ))}
                              {selectedMemories.length > 10 && (
                                <p className="text-xs text-muted-foreground text-center">
                                  +{selectedMemories.length - 10} more memories
                                </p>
                              )}
                            </div>
                          )}
                        </CardContent>
                      </Card>

                      {/* Knowledge Graph Nodes Touched */}
                      <Card>
                        <CardHeader className="pb-2">
                          <CardTitle className="text-sm flex items-center gap-2">
                            <Network className="h-4 w-4 text-green-500" />
                            Knowledge Graph Nodes
                          </CardTitle>
                        </CardHeader>
                        <CardContent>
                          {kgNodes.length === 0 ? (
                            <p className="text-sm text-muted-foreground italic">
                              No knowledge graph nodes available.
                            </p>
                          ) : (
                            <div className="flex flex-wrap gap-1.5">
                              {kgNodes.slice(0, 20).map((node) => (
                                <Badge
                                  key={node.id}
                                  variant="outline"
                                  className="text-xs"
                                >
                                  <Network className="h-3 w-3 mr-1" />
                                  {node.label || node.id.slice(0, 16)}
                                </Badge>
                              ))}
                              {kgNodes.length > 20 && (
                                <Badge variant="outline" className="text-xs">
                                  +{kgNodes.length - 20} more
                                </Badge>
                              )}
                            </div>
                          )}
                        </CardContent>
                      </Card>

                      {/* Timeline */}
                      <Card>
                        <CardHeader className="pb-2">
                          <CardTitle className="text-sm flex items-center gap-2">
                            <Activity className="h-4 w-4 text-purple-500" />
                            Event Timeline
                          </CardTitle>
                        </CardHeader>
                        <CardContent>
                          {selectedMessages.length === 0 ? (
                            <p className="text-sm text-muted-foreground italic">
                              No events to display.
                            </p>
                          ) : (
                            <div className="relative space-y-0">
                              {selectedMessages
                                .filter(
                                  (m) =>
                                    m.contentType === 'tool_call' ||
                                    m.contentType === 'assistant'
                                )
                                .slice(-20)
                                .map((msg, _) => (
                                  <div
                                    key={msg.id}
                                    className="flex items-start gap-3 pb-3 border-l-2 border-border pl-4 ml-2 relative"
                                  >
                                    <div className="absolute -left-[9px] top-1 h-4 w-4 rounded-full bg-primary/20 border-2 border-primary" />
                                    <div className="min-w-0">
                                      <div className="flex items-center gap-2">
                                        <Badge
                                          variant="outline"
                                          className={`text-[10px] ${roleBadgeColor(msg.contentType)}`}
                                        >
                                          {msg.contentType}
                                        </Badge>
                                        <span className="text-[10px] text-muted-foreground">
                                          {formatMemoryTimestamp(msg.createdAt)}
                                        </span>
                                      </div>
                                      <p className="text-xs mt-1 text-muted-foreground line-clamp-2">
                                        {msg.content.slice(0, 120)}
                                      </p>
                                    </div>
                                  </div>
                                ))}
                            </div>
                          )}
                        </CardContent>
                      </Card>
                    </div>
                  </TabsContent>
                </Tabs>
              </>
            )}
          </div>
        </div>
      )}
    </div>
  );
}

// ──────────────────────────────────────────────
// Sub-components extracted for readability
// ──────────────────────────────────────────────

function SessionDetailHeader({
  session,
  participants,
  duration,
}: {
  session: SessionRow;
  participants: PeerRow[];
  duration: string;
}) {
  return (
    <div className="space-y-2">
      <div className="flex items-start justify-between">
        <div>
          <h2 className="text-lg font-semibold">
            {session.name || 'Unnamed Session'}
          </h2>
          {session.summary && (
            <p className="text-sm text-muted-foreground mt-1 line-clamp-2">
              {session.summary}
            </p>
          )}
        </div>
        <Badge
          variant={session.updatedAt > Date.now() * 1000 - 3600_000_000 ? 'default' : 'secondary'}
          className="shrink-0 text-[10px]"
        >
          {session.updatedAt > Date.now() * 1000 - 3600_000_000 ? 'Active' : 'Inactive'}
        </Badge>
      </div>

      <div className="flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
        <span className="flex items-center gap-1">
          <Clock className="h-3 w-3" />
          {formatMemoryTimestamp(session.createdAt)}
        </span>
        <span className="flex items-center gap-1">
          <Activity className="h-3 w-3" />
          {duration}
        </span>
        <span className="flex items-center gap-1">
          <FileText className="h-3 w-3" />
          ID: {session.id.slice(0, 12)}…
        </span>
      </div>

      {/* Participant badges */}
      {participants.length > 0 && (
        <div className="flex flex-wrap gap-1.5 mt-1">
          {participants.map((peer) => (
            <ParticipantBadge key={peer.id} peer={peer} />
          ))}
        </div>
      )}
    </div>
  );
}

function SessionActions({
  onExport,
  onCreateNote,
  onReactivate,
}: {
  onExport: () => void;
  onCreateNote: () => void;
  onReactivate: () => void;
}) {
  return (
    <div className="flex items-center gap-2 mt-3 flex-wrap">
      <Button
        variant="outline"
        size="sm"
        onClick={onExport}
        className="text-xs h-8"
      >
        <Download className="h-3.5 w-3.5 mr-1" />
        Export Session
      </Button>
      <Button
        variant="outline"
        size="sm"
        onClick={onCreateNote}
        className="text-xs h-8"
      >
        <StickyNote className="h-3.5 w-3.5 mr-1" />
        Create Note
      </Button>
      <Button
        variant="secondary"
        size="sm"
        onClick={onReactivate}
        className="text-xs h-8"
      >
        <RefreshCw className="h-3.5 w-3.5 mr-1" />
        Re-activate
      </Button>
    </div>
  );
}
