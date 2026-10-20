import { createContext } from 'react';
import type { paths } from '../api/schema';

export type User = paths['/auth/me']['get']['responses'][200]['content']['application/json'];
export type UserRole = User['role'];

export interface AuthContextType {
  user: User | null;
  role: UserRole | null;
  isAuthenticated: boolean;
  isLoading: boolean;
  sessionExpired: boolean;
  login: (token: string) => Promise<void>;
  logout: () => Promise<void>;
  clearSessionExpired: () => void;
  refreshUser: () => Promise<User | null>;
}

export const AuthContext = createContext<AuthContextType | undefined>(undefined);
