import React, { useEffect, useState, useCallback, useMemo } from 'react';
import { api, getAccessToken, setAccessToken, setOnAuthFailure, refreshSession } from '../api/client';
import { useQueryClient } from '@tanstack/react-query';
import { AuthContext, type User } from './authContextDef';

export const AuthProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const [user, setUser] = useState<User | null>(null);
  const [isLoading, setIsLoading] = useState<boolean>(true);
  const [sessionExpired, setSessionExpired] = useState<boolean>(false);
  const queryClient = useQueryClient();

  const fetchCurrentUser = useCallback(async (): Promise<User | null> => {
    try {
      const { data, error } = await api.GET('/auth/me');
      if (error || !data) {
        setUser(null);
        return null;
      }
      setUser(data);
      return data;
    } catch {
      setUser(null);
      return null;
    }
  }, []);

  const handleAuthFailure = useCallback(() => {
    setAccessToken(null);
    setUser(null);
    setSessionExpired(true);
    queryClient.clear();
  }, [queryClient]);

  // Set auth failure callback on client
  useEffect(() => {
    setOnAuthFailure(handleAuthFailure);
    return () => {
      setOnAuthFailure(null);
    };
  }, [handleAuthFailure]);

  // Bootstrap session on app start via POST /auth/refresh
  useEffect(() => {
    let isMounted = true;

    async function initSession() {
      setIsLoading(true);
      try {
        const token = await refreshSession();
        if (token && isMounted) {
          await fetchCurrentUser();
        }
      } catch {
        if (isMounted) {
          setUser(null);
        }
      } finally {
        if (isMounted) {
          setIsLoading(false);
        }
      }
    }

    initSession();

    return () => {
      isMounted = false;
    };
  }, [fetchCurrentUser]);

  const login = useCallback(
    async (token: string) => {
      setAccessToken(token);
      setSessionExpired(false);
      await fetchCurrentUser();
    },
    [fetchCurrentUser]
  );

  const logout = useCallback(async () => {
    try {
      await api.POST('/auth/logout');
    } catch {
      // Ignore logout errors
    } finally {
      setAccessToken(null);
      setUser(null);
      queryClient.clear();
    }
  }, [queryClient]);

  const clearSessionExpired = useCallback(() => {
    setSessionExpired(false);
  }, []);

  const value = useMemo(
    () => ({
      user,
      role: user?.role || null,
      isAuthenticated: !!user && !!getAccessToken(),
      isLoading,
      sessionExpired,
      login,
      logout,
      clearSessionExpired,
      refreshUser: fetchCurrentUser,
    }),
    [user, isLoading, sessionExpired, login, logout, clearSessionExpired, fetchCurrentUser]
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
};
