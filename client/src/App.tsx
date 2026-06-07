import React, { Suspense, useEffect } from 'react';
import { Route, Switch } from 'wouter';
import Layout from '@/components/Layout';
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
          <Route path="/tours" component={Tours} />
          <Route path="/code-explorer" component={CodeExplorer} />
          <Route path="/trajectories" component={TrajectoryViz} />
          <Route path="/merge-candidates" component={MergeCandidates} />
          <Route path="/graph-viz" component={GraphViz} />
          <Route path="/block-graph" component={BlockGraph} />
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
    </AuthProvider>
  );
}
