import { useContext } from 'react';
import { AuthContext } from './authContextDef';

export { AuthProvider } from './AuthContext';
export type { User, UserRole } from './authContextDef';

export function useAuth() {
  const context = useContext(AuthContext);
  if (!context) {
    throw new Error('useAuth must be used within an AuthProvider');
  }
  return context;
}
