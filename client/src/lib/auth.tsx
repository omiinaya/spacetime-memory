import React, { createContext, useContext, useState, useEffect, useCallback, useMemo } from 'react';
import { useTable } from './useReactiveDb';
import { callReducer, getConnection } from './spacetimedb';

interface AccountRow {
  id: string;
  username: string;
  display_name: string;
  role: string;
  is_active: boolean;
}

export type AuthStatus =
  | { type: 'loading' }
  | { type: 'needs_account' }
  | { type: 'login' }
  | { type: 'authenticated'; account: AccountRow }
  ;

interface AuthContextValue {
  status: AuthStatus;
  register: (username: string, displayName: string, password: string) => Promise<void>;
  login: (username: string, password: string) => Promise<void>;
  logout: () => Promise<void>;
}

const AuthContext = createContext<AuthContextValue>(null!);

export function useAuth(): AuthContextValue {
  return useContext(AuthContext);
}

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const { data: accounts } = useTable<AccountRow>('account');
  const [status, setStatus] = useState<AuthStatus>({ type: 'loading' });
  const [myIdentity, setMyIdentity] = useState<string>('');

  // Extract current identity from connection
  useEffect(() => {
    const conn = getConnection();
    const checkIdentity = () => {
      try {
        if ((conn as any).identity?.toHexString) {
          setMyIdentity((conn as any).identity.toHexString().toLowerCase());
        }
      } catch {}
    };
    // Try once and retry after a delay (identity is set asynchronously)
    checkIdentity();
    const id = setTimeout(checkIdentity, 1000);
    return () => clearTimeout(id);
  }, []);

  // Recompute auth status when accounts or identity changes
  useEffect(() => {
    if (!myIdentity) {
      // Still waiting for identity
      return;
    }

    const myAccount = accounts?.find(
      (a: AccountRow) => a.id.toLowerCase() === myIdentity && a.is_active
    );

    if (myAccount) {
      setStatus({ type: 'authenticated', account: myAccount });
    } else if (accounts && accounts.length === 0) {
      // First run — no accounts exist
      setStatus({ type: 'needs_account' });
    } else {
      // Accounts exist but current identity isn't linked
      setStatus({ type: 'login' });
    }
  }, [accounts, myIdentity]);

  const register = useCallback(async (username: string, displayName: string, password: string) => {
    await callReducer('register', [username, displayName, password]);
    // Wait for subscription to sync
    await new Promise(r => setTimeout(r, 800));
    // Auto-login
    await callReducer('login', [username, password]);
    await new Promise(r => setTimeout(r, 800));
  }, []);

  const login = useCallback(async (username: string, password: string) => {
    await callReducer('login', [username, password]);
    await new Promise(r => setTimeout(r, 800));
  }, []);

  const logout = useCallback(async () => {
    await callReducer('logout', []);
    await new Promise(r => setTimeout(r, 500));
  }, []);

  const value = useMemo(() => ({ status, register, login, logout }), [status, register, login, logout]);

  return (
    <AuthContext.Provider value={value}>
      {children}
    </AuthContext.Provider>
  );
}
