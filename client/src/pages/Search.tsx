import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { Button } from '@/components/ui/button';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { Search as SearchIcon, SlidersHorizontal, Sparkles } from 'lucide-react';

export default function Search() {
  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-3xl font-bold tracking-tight">Search</h1>
        <p className="text-muted-foreground">Semantic and full-text search across all memories.</p>
      </div>

      <div className="flex gap-4">
        <div className="relative flex-1">
          <SearchIcon className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
          <Input placeholder="Search across memories, documents, and graph nodes..." className="pl-9 h-12 text-base" />
        </div>
        <Button variant="outline" size="icon" className="h-12 w-12 shrink-0">
          <SlidersHorizontal className="h-4 w-4" />
        </Button>
      </div>

      <Tabs defaultValue="semantic">
        <TabsList>
          <TabsTrigger value="semantic">
            <Sparkles className="mr-2 h-4 w-4" />
            Semantic Search
          </TabsTrigger>
          <TabsTrigger value="fulltext">
            <SearchIcon className="mr-2 h-4 w-4" />
            Full-Text
          </TabsTrigger>
        </TabsList>
        <TabsContent value="semantic">
          <Card>
            <CardHeader>
              <CardTitle className="text-lg">Semantic Search</CardTitle>
            </CardHeader>
            <CardContent>
              <div className="flex h-40 items-center justify-center rounded-lg border border-dashed border-border bg-muted/30">
                <div className="text-center">
                  <Sparkles className="mx-auto h-8 w-8 text-muted-foreground/50" />
                  <p className="mt-2 text-sm text-muted-foreground">Enter a query above to search semantically</p>
                  <p className="text-xs text-muted-foreground/60">Results will show relevance scores and source contexts</p>
                </div>
              </div>
            </CardContent>
          </Card>
        </TabsContent>
        <TabsContent value="fulltext">
          <Card>
            <CardHeader>
              <CardTitle className="text-lg">Full-Text Search</CardTitle>
            </CardHeader>
            <CardContent>
              <p className="text-sm text-muted-foreground">Traditional keyword-based search across all indexed text. Full implementation coming soon.</p>
            </CardContent>
          </Card>
        </TabsContent>
      </Tabs>
    </div>
  );
}
