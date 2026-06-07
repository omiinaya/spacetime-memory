import React from 'react';
import { Link, useRoute } from 'wouter';
import { cn } from '@/lib/utils';
import {
  LayoutDashboard,
  Users,
  Monitor,
  Network,
  Database,
  FileText,
  Search,
  Settings,
  Menu,
  X,
  Sparkles,
  StickyNote,
  CalendarDays,
  LogOut,
  User,
  Route,
  Code2,
  GitFork,
  GitMerge,
} from 'lucide-react';
import { Button } from '@/components/ui/button';
import { useAuth } from '@/lib/auth';

interface NavItem {
  href: string;
  label: string;
  icon: React.ElementType;
}

const navItems: NavItem[] = [
  { href: '/', label: 'Dashboard', icon: LayoutDashboard },
  { href: '/daily', label: 'Daily Notes', icon: CalendarDays },
  { href: '/notes', label: 'Notes', icon: StickyNote },
  { href: '/graph/notes', label: 'Note Graph', icon: Network },
  { href: '/peers', label: 'Peers', icon: Users },
  { href: '/sessions', label: 'Sessions', icon: Monitor },
  { href: '/graph', label: 'Knowledge Graph', icon: Network },
  { href: '/memories', label: 'Memory Browser', icon: Database },
  { href: '/documents', label: 'Documents', icon: FileText },
  { href: '/search', label: 'Search', icon: Search },
  { href: '/query', label: 'Smart Query', icon: Sparkles },
  { href: '/tours', label: 'Tours', icon: Route },
  { href: '/code-explorer', label: 'Code Explorer', icon: Code2 },
  { href: '/trajectories', label: 'Trajectories', icon: GitFork },
  { href: '/merge-candidates', label: 'Merge Candidates', icon: GitMerge },
  { href: '/settings', label: 'Settings', icon: Settings },
];

function Sidebar({ collapsed, onToggle }: { collapsed: boolean; onToggle: () => void }) {
  return (
    <aside
      className={cn(
        'fixed left-0 top-0 z-40 flex h-screen flex-col border-r border-border bg-card transition-all duration-300',
        collapsed ? 'w-16' : 'w-60'
      )}
    >
      {/* Logo area */}
      <div className="flex h-14 items-center justify-between border-b border-border px-4">
        {!collapsed && (
          <div className="flex items-center gap-2">
            <Sparkles className="h-5 w-5 text-primary" />
            <span className="font-semibold tracking-tight">Spacetime</span>
          </div>
        )}
        {collapsed && (
          <Sparkles className="mx-auto h-5 w-5 text-primary" />
        )}
        <Button
          variant="ghost"
          size="icon"
          onClick={onToggle}
          className="h-8 w-8 shrink-0"
        >
          {collapsed ? <Menu className="h-4 w-4" /> : <X className="h-4 w-4" />}
        </Button>
      </div>

      {/* Navigation */}
      <nav className="flex-1 overflow-y-auto p-2">
        <ul className="space-y-1">
          {navItems.map((item) => {
            const [isActive] = useRoute(item.href === '/' ? '/' : `${item.href}/?`);
            // Also match exact route for sub-pages
            const [isExact] = useRoute(item.href);
            const active = isActive || isExact;
            return (
              <li key={item.href}>
                <Link
                  href={item.href}
                  className={cn(
                    'flex items-center gap-3 rounded-lg px-3 py-2 text-sm font-medium transition-colors',
                    active
                      ? 'bg-accent text-accent-foreground'
                      : 'text-muted-foreground hover:bg-accent/50 hover:text-accent-foreground'
                  )}
                >
                  <item.icon className="h-5 w-5 shrink-0" />
                  {!collapsed && <span>{item.label}</span>}
                </Link>
              </li>
            );
          })}
        </ul>
      </nav>

      {/* Footer */}
      {!collapsed && (
        <div className="border-t border-border p-3 space-y-2">
          <UserInfo />
          <p className="text-xs text-muted-foreground">Spacetime Memory v0.1</p>
        </div>
      )}
    </aside>
  );
}

function UserInfo() {
  const { status, logout } = useAuth();
  if (status.type !== 'authenticated') return null;

  return (
    <div className="space-y-1">
      <div className="flex items-center gap-2 text-xs text-muted-foreground">
        <User className="h-3 w-3" />
        <span className="truncate font-medium">{status.account.display_name || status.account.username}</span>
        <span className="text-[10px] bg-muted px-1 rounded">{status.account.role}</span>
      </div>
      <button
        onClick={logout}
        className="flex items-center gap-1.5 text-[10px] text-muted-foreground/60 hover:text-destructive transition-colors"
      >
        <LogOut className="h-3 w-3" />
        Logout
      </button>
    </div>
  );
}

export default function Layout({ children }: { children: React.ReactNode }) {
  const [sidebarCollapsed, setSidebarCollapsed] = React.useState(false);

  return (
    <div className="min-h-screen bg-background">
      <Sidebar
        collapsed={sidebarCollapsed}
        onToggle={() => setSidebarCollapsed((v) => !v)}
      />
      <main
        className={cn(
          'min-h-screen transition-all duration-300',
          sidebarCollapsed ? 'ml-16' : 'ml-60'
        )}
      >
        <div className="container mx-auto p-6 lg:p-8">{children}</div>
      </main>
    </div>
  );
}
