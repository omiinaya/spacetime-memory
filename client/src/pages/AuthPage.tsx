import { useState } from 'react';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Loader2, Sparkles, LogIn, UserPlus } from 'lucide-react';
import { useAuth } from '@/lib/auth';

export default function AuthPage() {
  const { status, register, login } = useAuth();
  const needsRegister = status.type === 'needs_account';

  const [mode, setMode] = useState<'login' | 'register'>(needsRegister ? 'register' : 'login');
  const [username, setUsername] = useState('');
  const [displayName, setDisplayName] = useState('');
  const [password, setPassword] = useState('');
  const [confirmPassword, setConfirmPassword] = useState('');
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError('');

    if (!username.trim()) { setError('Username is required'); return; }
    if (password.length < 6) { setError('Password must be at least 6 characters'); return; }

    if (mode === 'register') {
      if (password !== confirmPassword) {
        setError('Passwords do not match');
        return;
      }
      setLoading(true);
      try {
        await register(username.trim(), displayName.trim() || username.trim(), password);
      } catch (e: any) {
        setError(e.message || 'Registration failed');
      } finally {
        setLoading(false);
      }
    } else {
      setLoading(true);
      try {
        await login(username.trim(), password);
      } catch (e: any) {
        setError(e.message || 'Login failed');
      } finally {
        setLoading(false);
      }
    }
  };

  return (
    <div className="min-h-screen flex items-center justify-center bg-background p-4">
      <Card className="w-full max-w-md">
        <CardHeader className="text-center pb-2">
          <div className="flex justify-center mb-3">
            <Sparkles className="h-10 w-10 text-primary" />
          </div>
          <CardTitle className="text-2xl">Spacetime Memory</CardTitle>
          <CardDescription>
            {mode === 'register'
              ? 'Create your account to get started'
              : 'Sign in to access your memory'}
          </CardDescription>
        </CardHeader>
        <CardContent>
          <form onSubmit={handleSubmit} className="space-y-4">
            {error && (
              <div className="bg-destructive/10 text-destructive text-sm rounded-md px-3 py-2">
                {error}
              </div>
            )}

            <div className="space-y-2">
              <label className="text-sm font-medium" htmlFor="username">Username</label>
              <Input
                id="username"
                placeholder="Enter your username"
                value={username}
                onChange={e => setUsername(e.target.value)}
                disabled={loading}
                autoFocus
              />
            </div>

            {mode === 'register' && (
              <div className="space-y-2">
                <label className="text-sm font-medium" htmlFor="displayName">Display Name (optional)</label>
                <Input
                  id="displayName"
                  placeholder="How others see you"
                  value={displayName}
                  onChange={e => setDisplayName(e.target.value)}
                  disabled={loading}
                />
              </div>
            )}

            <div className="space-y-2">
              <label className="text-sm font-medium" htmlFor="password">Password</label>
              <Input
                id="password"
                type="password"
                placeholder="Enter your password"
                value={password}
                onChange={e => setPassword(e.target.value)}
                disabled={loading}
              />
            </div>

            {mode === 'register' && (
              <div className="space-y-2">
                <label className="text-sm font-medium" htmlFor="confirmPassword">Confirm Password</label>
                <Input
                  id="confirmPassword"
                  type="password"
                  placeholder="Re-enter your password"
                  value={confirmPassword}
                  onChange={e => setConfirmPassword(e.target.value)}
                  disabled={loading}
                />
              </div>
            )}

            <Button type="submit" className="w-full" disabled={loading}>
              {loading ? (
                <><Loader2 className="mr-2 h-4 w-4 animate-spin" /> Processing...</>
              ) : mode === 'register' ? (
                <><UserPlus className="mr-2 h-4 w-4" /> Create Account</>
              ) : (
                <><LogIn className="mr-2 h-4 w-4" /> Sign In</>
              )}
            </Button>

            {!needsRegister && (
              <div className="text-center text-sm text-muted-foreground">
                {mode === 'login' ? (
                  <>Don't have an account?{' '}
                    <button
                      type="button"
                      className="text-primary underline hover:no-underline"
                      onClick={() => { setMode('register'); setError(''); }}
                    >
                      Register
                    </button>
                  </>
                ) : (
                  <>Already have an account?{' '}
                    <button
                      type="button"
                      className="text-primary underline hover:no-underline"
                      onClick={() => { setMode('login'); setError(''); }}
                    >
                      Sign In
                    </button>
                  </>
                )}
              </div>
            )}
          </form>
        </CardContent>
      </Card>
    </div>
  );
}
