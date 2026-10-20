import React, { useState } from 'react';
import { NavLink, Outlet, useNavigate } from 'react-router-dom';
import { useAuth } from '../../auth/useAuth';
import {
  FileText,
  LayoutDashboard,
  Files,
  Inbox,
  FileSpreadsheet,
  LogOut,
  Menu,
  X,
  Shield,
} from 'lucide-react';
import { clsx } from 'clsx';

export const AppLayout: React.FC = () => {
  const { user, role, logout } = useAuth();
  const navigate = useNavigate();
  const [mobileMenuOpen, setMobileMenuOpen] = useState(false);

  const handleLogout = async () => {
    await logout();
    navigate('/login', { replace: true });
  };

  const navItems = [
    {
      to: '/',
      label: 'Dashboard',
      icon: <LayoutDashboard className="w-4 h-4" />,
      allowedRoles: ['admin', 'reviewer', 'viewer'],
    },
    {
      to: '/documents',
      label: 'Documents',
      icon: <Files className="w-4 h-4" />,
      allowedRoles: ['admin', 'reviewer', 'viewer'],
    },
    {
      to: '/review',
      label: 'Review Queue',
      icon: <Inbox className="w-4 h-4" />,
      allowedRoles: ['admin', 'reviewer'],
    },
    {
      to: '/exports',
      label: 'Exports',
      icon: <FileSpreadsheet className="w-4 h-4" />,
      allowedRoles: ['admin', 'reviewer', 'viewer'],
    },
  ];

  const visibleNavItems = navItems.filter(
    (item) => !role || item.allowedRoles.includes(role)
  );

  return (
    <div className="min-h-screen bg-gray-50 flex flex-col">
      {/* Top Navbar */}
      <header className="bg-white border-b border-gray-200/80 sticky top-0 z-30">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
          <div className="flex justify-between h-16">
            <div className="flex items-center gap-8">
              {/* Brand */}
              <div className="flex items-center gap-2.5">
                <div className="w-9 h-9 rounded-lg bg-sky-600 text-white flex items-center justify-center shadow-sm">
                  <FileText className="w-5 h-5" />
                </div>
                <span className="text-xl font-bold tracking-tight text-gray-900">
                  DocFlow
                </span>
              </div>

              {/* Desktop Nav Links */}
              <nav className="hidden md:flex space-x-1" aria-label="Main Navigation">
                {visibleNavItems.map((item) => (
                  <NavLink
                    key={item.to}
                    to={item.to}
                    end={item.to === '/'}
                    className={({ isActive }) =>
                      clsx(
                        'flex items-center gap-2 px-3 py-2 rounded-lg text-sm font-medium transition-colors',
                        isActive
                          ? 'bg-sky-50 text-sky-700'
                          : 'text-gray-600 hover:text-gray-900 hover:bg-gray-100'
                      )
                    }
                  >
                    {item.icon}
                    <span>{item.label}</span>
                  </NavLink>
                ))}
              </nav>
            </div>

            {/* Desktop User Info & Logout */}
            <div className="hidden md:flex items-center gap-4">
              <div className="flex flex-col text-right">
                <span className="text-sm font-medium text-gray-900 leading-tight">
                  {user?.email}
                </span>
                <div className="flex items-center justify-end gap-1.5 mt-0.5">
                  <span
                    className={clsx(
                      'inline-flex items-center gap-1 text-[11px] font-semibold px-2 py-0.5 rounded-full capitalize',
                      role === 'admin' && 'bg-purple-50 text-purple-700 border border-purple-200',
                      role === 'reviewer' && 'bg-blue-50 text-blue-700 border border-blue-200',
                      role === 'viewer' && 'bg-gray-100 text-gray-700 border border-gray-300'
                    )}
                    data-testid="user-role-badge"
                  >
                    <Shield className="w-3 h-3" />
                    {role}
                  </span>
                  <span className="text-xs text-gray-400">
                    Org: {user?.org_id.slice(0, 8)}…
                  </span>
                </div>
              </div>

              <button
                onClick={handleLogout}
                className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg border border-gray-300 text-sm font-medium text-gray-700 bg-white hover:bg-gray-50 focus:outline-none focus:ring-2 focus:ring-sky-500 transition-colors shadow-sm"
                aria-label="Log out"
              >
                <LogOut className="w-4 h-4 text-gray-500" />
                <span>Logout</span>
              </button>
            </div>

            {/* Mobile menu button */}
            <div className="flex items-center md:hidden">
              <button
                onClick={() => setMobileMenuOpen(!mobileMenuOpen)}
                className="p-2 rounded-md text-gray-500 hover:text-gray-700 hover:bg-gray-100 focus:outline-none"
                aria-label="Toggle mobile menu"
              >
                {mobileMenuOpen ? <X className="w-6 h-6" /> : <Menu className="w-6 h-6" />}
              </button>
            </div>
          </div>
        </div>

        {/* Mobile menu */}
        {mobileMenuOpen && (
          <div className="md:hidden border-b border-gray-200 bg-white px-4 pt-2 pb-4 space-y-2">
            <div className="py-2 border-b border-gray-100">
              <p className="text-sm font-medium text-gray-900">{user?.email}</p>
              <p className="text-xs text-gray-500 capitalize">Role: {role}</p>
            </div>
            {visibleNavItems.map((item) => (
              <NavLink
                key={item.to}
                to={item.to}
                end={item.to === '/'}
                onClick={() => setMobileMenuOpen(false)}
                className={({ isActive }) =>
                  clsx(
                    'flex items-center gap-2 px-3 py-2 rounded-md text-base font-medium',
                    isActive ? 'bg-sky-50 text-sky-700' : 'text-gray-600 hover:bg-gray-100'
                  )
                }
              >
                {item.icon}
                <span>{item.label}</span>
              </NavLink>
            ))}
            <button
              onClick={() => {
                setMobileMenuOpen(false);
                handleLogout();
              }}
              className="w-full flex items-center gap-2 px-3 py-2 text-rose-600 rounded-md font-medium text-base hover:bg-rose-50"
            >
              <LogOut className="w-5 h-5" />
              <span>Logout</span>
            </button>
          </div>
        )}
      </header>

      {/* Main Content Area */}
      <main className="flex-1 max-w-7xl w-full mx-auto px-4 sm:px-6 lg:px-8 py-8">
        <Outlet />
      </main>
    </div>
  );
};
