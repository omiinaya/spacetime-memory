import React, { Suspense, useEffect } from 'react';
import { Route, Switch } from 'wouter';
import { Toaster } from 'sonner';
import Layout from '@/components/Layout';
import { ErrorBoundary } from '@/components/ErrorBoundary';
import { Loader2, Sparkles } from 'lucide-react';
import { initReactiveDb } from '@/lib/useReactiveDb';
import { AuthProvider, useAuth } from '@/lib/auth';

const AuthPage = React.lazy(() => import('@/pages/AuthPage'));
const Dashboard = React.lazy(() => import('@/pages/Dashboard'));
const Peers = React.lazy(() => import('@/pages/Peers'));
const Sessions = React.lazy(() => import('@/pages/Sessions'));
const KnowledgeGraph = React.lazy(() => import('@/pages/KnowledgeGraph'));
const MemoryBrowser = React.lazy(() => import('@/pages/MemoryBrowser'));
const Documents = React.lazy(() => import('@/pages/Documents'));
const Search = React.lazy(() => import('@/pages/Search'));
const Settings = React.lazy(() => import('@/pages/Settings'));
const DailyNotes = React.lazy(() => import('@/pages/DailyNotes'));
const NotesList = React.lazy(() => import('@/pages/NotesList'));
const NoteEditor = React.lazy(() => import('@/pages/NoteEditor'));
const NoteGraph = React.lazy(() => import('@/pages/NoteGraph'));
const SmartQuery = React.lazy(() => import('@/pages/SmartQuery'));
const Tours = React.lazy(() => import('@/pages/Tours'));
const CodeExplorer = React.lazy(() => import('@/pages/CodeExplorer'));
const TrajectoryViz = React.lazy(() => import('@/pages/TrajectoryViz'));
const MergeCandidates = React.lazy(() => import('@/pages/MergeCandidates'));
const GraphViz = React.lazy(() => import('@/pages/GraphViz'));
const BlockGraph = React.lazy(() => import('@/pages/BlockGraph'));
const SessionReasoning = React.lazy(() => import('@/pages/SessionReasoning'));
const DirectoryBrowser = React.lazy(() => import('@/pages/DirectoryBrowser'));
const TrustDashboard = React.lazy(() => import('@/pages/TrustDashboard'));
const ProxyMetricsDashboard = React.lazy(() => import('@/pages/ProxyMetricsDashboard'));
const MemoryMetaEditor = React.lazy(() => import('@/pages/MemoryMetaEditor'));
const WebhooksPage = React.lazy(() => import('@/pages/WebhooksPage'));
const ObservationsPage = React.lazy(() => import('@/pages/ObservationsPage'));
const ContextTreeEditor = React.lazy(() => import('@/pages/ContextTreeEditor'));
const ReviewPage = React.lazy(() => import('@/pages/ReviewPage'));
const ExportImportPage = React.lazy(() => import('@/pages/ExportImportPage'));
const TaskQueuePage = React.lazy(() => import('@/pages/TaskQueuePage'));
const PipelinePage = React.lazy(() => import('@/pages/PipelinePage'));
const RBACPage = React.lazy(() => import('@/pages/RBACPage'));
const SkillsModsPage = React.lazy(() => import('@/pages/SkillsModsPage'));
const OntologyPage = React.lazy(() => import('@/pages/OntologyPage'));
const MetricsDashboardPage = React.lazy(() => import('@/pages/MetricsDashboardPage'));
const ReflectionLoopPage = React.lazy(() => import('@/pages/ReflectionLoopPage'));
const ReasoningTiersPage = React.lazy(() => import('@/pages/ReasoningTiersPage'));
const CognitiveOpsPage = React.lazy(() => import('@/pages/CognitiveOpsPage'));
const MemfsPage = React.lazy(() => import('@/pages/MemfsPage'));
const PatternDetectionPage = React.lazy(() => import('@/pages/PatternDetectionPage'));

function LoadingFallback() {
  return (
    <div className="flex h-screen items-center justify-center bg-background">
      <div className="text-center">
        <Sparkles className="mx-auto h-8 w-8 animate-pulse text-primary mb-4" />
        <Loader2 className="mx-auto h-6 w-6 animate-spin text-muted-foreground" />
        <p className="mt-2 text-sm text-muted-foreground">Loading...</p>
      </div>
    </div>
  );
}

function AuthenticatedApp() {
  const { status } = useAuth();

  // Still loading auth state
  if (status.type === 'loading') {
    return <LoadingFallback />;
  }

  // Not authenticated — show auth page
  if (status.type === 'needs_account' || status.type === 'login') {
    return (
      <Suspense fallback={<LoadingFallback />}>
        <AuthPage />
      </Suspense>
    );
  }

  // Authenticated — show the main app
  return (
    <Layout>
      <ErrorBoundary>
        <Suspense fallback={<LoadingFallback />}>
          <Switch>
            <Route path="/" component={Dashboard} />
          <Route path="/peers" component={Peers} />
          <Route path="/sessions" component={Sessions} />
          <Route path="/graph" component={KnowledgeGraph} />
          <Route path="/memories" component={MemoryBrowser} />
          <Route path="/documents" component={Documents} />
          <Route path="/search" component={Search} />
          <Route path="/settings" component={Settings} />
          <Route path="/daily" component={DailyNotes} />
          <Route path="/notes" component={NotesList} />
          <Route path="/notes/new" component={NoteEditor} />
          <Route path="/notes/:id" component={NoteEditor} />
          <Route path="/graph/notes" component={NoteGraph} />
          <Route path="/query" component={SmartQuery} />
          <Route path="/trust-dashboard" component={TrustDashboard} />
          <Route path="/proxy-metrics" component={ProxyMetricsDashboard} />
          <Route path="/tours" component={Tours} />
          <Route path="/code-explorer" component={CodeExplorer} />
          <Route path="/trajectories" component={TrajectoryViz} />
          <Route path="/merge-candidates" component={MergeCandidates} />
          <Route path="/graph-viz" component={GraphViz} />
          <Route path="/block-graph" component={BlockGraph} />
          <Route path="/session-reasoning" component={SessionReasoning} />
          <Route path="/directory-browser" component={DirectoryBrowser} />
          <Route path="/memory-meta" component={MemoryMetaEditor} />
          <Route path="/webhooks" component={WebhooksPage} />
          <Route path="/observations" component={ObservationsPage} />
          <Route path="/context-tree" component={ContextTreeEditor} />
          <Route path="/review" component={ReviewPage} />
          <Route path="/export-import" component={ExportImportPage} />
          <Route path="/task-queue" component={TaskQueuePage} />
          <Route path="/pipelines" component={PipelinePage} />
          <Route path="/rbac" component={RBACPage} />
          <Route path="/skills-mods" component={SkillsModsPage} />
          <Route path="/ontology" component={OntologyPage} />
          <Route path="/metrics" component={MetricsDashboardPage} />
          <Route path="/reflection-loop" component={ReflectionLoopPage} />
          <Route path="/reasoning-tiers" component={ReasoningTiersPage} />
          <Route path="/cognitive-ops" component={CognitiveOpsPage} />
          <Route path="/memfs" component={MemfsPage} />
          <Route path="/pattern-detection" component={PatternDetectionPage} />
          <Route>
            <div className="flex h-[60vh] items-center justify-center">
              <div className="text-center">
                <h2 className="text-2xl font-bold">404</h2>
                <p className="text-muted-foreground">Page not found</p>
              </div>
            </div>
          </Route>
        </Switch>
      </Suspense>
      </ErrorBoundary>
    </Layout>
  );
}

export default function App() {
  // Connect + subscribe all tables once on mount
  useEffect(() => {
    initReactiveDb();
  }, []);

  return (
    <AuthProvider>
      <AuthenticatedApp />
      <Toaster richColors theme="dark" position="bottom-right" />
    </AuthProvider>
  );
}
