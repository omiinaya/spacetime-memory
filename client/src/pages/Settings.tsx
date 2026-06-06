import { useState, useEffect } from 'react';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { Button } from '@/components/ui/button';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { Badge } from '@/components/ui/badge';
import { Palette, Database, Sliders, Check } from 'lucide-react';

const SETTINGS_KEY = 'spacetime-memory-settings';

interface Settings {
  nodeName: string;
  apiEndpoint: string;
  refreshInterval: number;
}

function defaultSettings(): Settings {
  return {
    nodeName: 'spacetime-memory-node',
    apiEndpoint: 'http://localhost:3001',
    refreshInterval: 5,
  };
}

function loadSettings(): Settings {
  try {
    const raw = localStorage.getItem(SETTINGS_KEY);
    if (raw) return { ...defaultSettings(), ...JSON.parse(raw) };
  } catch { /* ignore */ }
  return defaultSettings();
}

function saveSettings(s: Settings) {
  localStorage.setItem(SETTINGS_KEY, JSON.stringify(s));
}

export default function Settings() {
  const [settings, setSettings] = useState<Settings>(defaultSettings);
  const [saved, setSaved] = useState(false);

  useEffect(() => {
    setSettings(loadSettings());
  }, []);

  const handleSave = () => {
    saveSettings(settings);
    setSaved(true);
    setTimeout(() => setSaved(false), 2000);
  };

  const update = (key: keyof Settings, value: string | number) => {
    setSettings((prev) => ({ ...prev, [key]: value }));
  };

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-3xl font-bold tracking-tight">Settings</h1>
        <p className="text-muted-foreground">Configure your spacetime memory node preferences.</p>
      </div>

      <Tabs defaultValue="general">
        <TabsList className="flex-wrap">
          <TabsTrigger value="general">
            <Sliders className="mr-2 h-4 w-4" />
            General
          </TabsTrigger>
          <TabsTrigger value="appearance">
            <Palette className="mr-2 h-4 w-4" />
            Appearance
          </TabsTrigger>
          <TabsTrigger value="storage">
            <Database className="mr-2 h-4 w-4" />
            Storage
          </TabsTrigger>
        </TabsList>

        {/* General */}
        <TabsContent value="general">
          <Card>
            <CardHeader>
              <CardTitle className="text-lg">General Settings</CardTitle>
            </CardHeader>
            <CardContent className="space-y-4">
              <div className="space-y-2">
                <label className="text-sm font-medium">SpacetimeDB Endpoint</label>
                <Input
                  placeholder="http://localhost:3001"
                  className="max-w-md font-mono text-sm"
                  value={settings.apiEndpoint}
                  onChange={(e) => update('apiEndpoint', e.target.value)}
                />
                <p className="text-xs text-muted-foreground">
                  HTTP URL of the SpacetimeDB standalone server.
                </p>
              </div>
              <div className="space-y-2">
                <label className="text-sm font-medium">Polling Interval (seconds)</label>
                <Input
                  placeholder="5"
                  type="number"
                  min={1}
                  max={60}
                  className="max-w-[120px]"
                  value={settings.refreshInterval}
                  onChange={(e) => update('refreshInterval', Math.max(1, Math.min(60, parseInt(e.target.value) || 5)))}
                />
                <p className="text-xs text-muted-foreground">
                  How often the dashboard refreshes data from SpacetimeDB.
                </p>
              </div>
              <div className="flex items-center gap-3">
                <Button onClick={handleSave}>
                  {saved ? (
                    <span className="flex items-center gap-1">
                      <Check className="h-4 w-4" /> Saved
                    </span>
                  ) : (
                    'Save Changes'
                  )}
                </Button>
                {saved && (
                  <span className="text-xs text-green-500 flex items-center gap-1">
                    <Check className="h-3 w-3" /> Settings saved locally
                  </span>
                )}
              </div>
            </CardContent>
          </Card>
        </TabsContent>

        {/* Appearance */}
        <TabsContent value="appearance">
          <Card>
            <CardHeader>
              <CardTitle className="text-lg">Appearance</CardTitle>
            </CardHeader>
            <CardContent>
              <div className="flex items-center justify-between rounded-lg border border-border p-4">
                <div>
                  <p className="font-medium">Dark Mode</p>
                  <p className="text-sm text-muted-foreground">Currently active (default)</p>
                </div>
                <Badge>Dark</Badge>
              </div>
            </CardContent>
          </Card>
        </TabsContent>

        {/* Storage */}
        <TabsContent value="storage">
          <Card>
            <CardHeader>
              <CardTitle className="text-lg">Storage</CardTitle>
            </CardHeader>
            <CardContent>
              <p className="text-sm text-muted-foreground">
                Storage is managed by SpacetimeDB. Check the SpacetimeDB data directory
                for database size and maintenance.
              </p>
              <div className="mt-4 rounded-lg border border-border p-3 bg-muted/30">
                <p className="text-xs font-mono text-muted-foreground">
                  ~/.local/share/spacetime/data/
                </p>
              </div>
            </CardContent>
          </Card>
        </TabsContent>
      </Tabs>
    </div>
  );
}
