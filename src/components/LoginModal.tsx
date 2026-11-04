import React, { useState, useEffect } from 'react';
import { useStore } from '../context/StoreContext';
import {
  Lock,
  User,
  AlertCircle,
  RefreshCw,
  Eye,
  EyeOff,
  Settings,
  CheckCircle2,
  Factory,
  Truck,
  Scale,
  ShieldCheck,
  Building2,
} from 'lucide-react';

const REMEMBERED_USER_KEY = 'ks_remembered_username';

export const LoginModal: React.FC = () => {
  const {
    login,
    backendUrl,
    updateBackendUrl,
    isBackendConnected,
    isGoogleSheetsConnected,
    persistentWritesEnabled,
  } = useStore();

  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [rememberUser, setRememberUser] = useState(false);
  const [showPassword, setShowPassword] = useState(false);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<{ message: string; type: 'auth' | 'network' | 'forbidden' } | null>(null);
  const [showServerConfig, setShowServerConfig] = useState(false);
  const [customUrl, setCustomUrl] = useState(backendUrl);

  // Restore remembered username on mount if previously chosen
  useEffect(() => {
    if (typeof window !== 'undefined') {
      try {
        const saved = localStorage.getItem(REMEMBERED_USER_KEY);
        if (saved) {
          setUsername(saved);
          setRememberUser(true);
        }
      } catch {
        // ignore localStorage access limitations
      }
    }
  }, []);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (isLoading) return;
    setError(null);

    const cleanUser = username.trim();
    if (!cleanUser || !password) {
      setError({
        message: 'Please enter both your User ID / Username and Password to proceed.',
        type: 'auth',
      });
      return;
    }

    // Save or clear remembered username preference (strictly username only, never password)
    if (typeof window !== 'undefined') {
      try {
        if (rememberUser) {
          localStorage.setItem(REMEMBERED_USER_KEY, cleanUser);
        } else {
          localStorage.removeItem(REMEMBERED_USER_KEY);
        }
      } catch {
        // ignore
      }
    }

    setIsLoading(true);
    try {
      await login(cleanUser, password);
    } catch (err: unknown) {
      const rawMsg = err instanceof Error ? err.message : String(err);
      const lower = rawMsg.toLowerCase();

      if (
        lower.includes('401') ||
        lower.includes('invalid') ||
        lower.includes('unauthorized') ||
        lower.includes('credentials')
      ) {
        setError({
          message: 'The username or password you entered is incorrect. Please check your credentials and try again.',
          type: 'auth',
        });
      } else if (lower.includes('403') || lower.includes('deactivated') || lower.includes('legacy')) {
        setError({
          message: rawMsg.replace(/HTTP \d+:\s*/i, ''),
          type: 'forbidden',
        });
      } else if (lower.includes('429') || lower.includes('quota') || lower.includes('too many')) {
        setError({
          message: 'Too many sign-in attempts detected. Please wait 60 seconds before trying again.',
          type: 'network',
        });
      } else if (
        lower.includes('503') ||
        lower.includes('failed to fetch') ||
        lower.includes('network') ||
        lower.includes('timeout') ||
        lower.includes('offline') ||
        lower.includes('standby')
      ) {
        setError({
          message:
            'The ERP server is currently unreachable or resuming from standby. Please check your network connection or retry in a few moments.',
          type: 'network',
        });
      } else {
        setError({
          message: rawMsg || 'Authentication failed. Please verify your connection and try again.',
          type: 'auth',
        });
      }
    } finally {
      setIsLoading(false);
    }
  };

  const handleSaveBackendUrl = (e: React.FormEvent) => {
    e.preventDefault();
    if (customUrl.trim()) {
      updateBackendUrl(customUrl.trim());
      setShowServerConfig(false);
    }
  };

  // Truthful live connection status indicator
  const getConnectionState = () => {
    if (!isBackendConnected) {
      return {
        label: 'API Server Standby',
        dot: 'bg-amber-400',
        text: 'text-amber-700',
        bg: 'bg-amber-50 border-amber-200',
      };
    }
    if (!isGoogleSheetsConnected) {
      return {
        label: 'API Connected · Sheets Offline',
        dot: 'bg-amber-400',
        text: 'text-amber-700',
        bg: 'bg-amber-50 border-amber-200',
      };
    }
    if (!persistentWritesEnabled) {
      return {
        label: 'API Connected · Storage Standby',
        dot: 'bg-amber-400 animate-pulse',
        text: 'text-amber-800',
        bg: 'bg-amber-50 border-amber-300',
      };
    }
    return {
      label: 'System Online · Storage Verified',
      dot: 'bg-emerald-500',
      text: 'text-emerald-800',
      bg: 'bg-emerald-50 border-emerald-200',
    };
  };

  const connState = getConnectionState();

  return (
    <div className="min-h-screen w-full bg-[#FAF8F5] flex flex-col lg:flex-row items-stretch select-none">
      {/* ------------------------------------------------------------------ */}
      {/* LEFT SECTION: BRAND IDENTITY & OPERATIONAL PILLARS (Desktop)       */}
      {/* ------------------------------------------------------------------ */}
      <div className="hidden lg:flex lg:w-1/2 xl:w-5/12 bg-gradient-to-br from-emerald-950 via-emerald-900 to-slate-950 text-white flex-col justify-between p-12 xl:p-16 relative overflow-hidden shrink-0 shadow-2xl">
        {/* Subtle decorative background watermark */}
        <div className="absolute -right-20 -bottom-20 w-96 h-96 rounded-full bg-emerald-600/10 blur-3xl pointer-events-none" />
        <div className="absolute -left-20 -top-20 w-80 h-80 rounded-full bg-emerald-500/10 blur-3xl pointer-events-none" />

        {/* Top Header: Brand Emblem & ERP Identity */}
        <div className="relative z-10">
          <div className="flex items-center gap-3.5 mb-8">
            <div className="w-12 h-12 rounded-xl bg-white text-emerald-900 flex items-center justify-center font-black text-xl shadow-lg border border-amber-200/40">
              KS
            </div>
            <div>
              <span className="text-xs font-extrabold tracking-widest text-emerald-300 uppercase block">
                Kawad Swad Udhyog
              </span>
              <span className="text-xl font-bold tracking-tight text-white block">
                Enterprise Resource Planning
              </span>
            </div>
          </div>

          <div className="inline-flex items-center gap-2 px-3 py-1 rounded-full text-xs font-semibold bg-emerald-800/60 border border-emerald-500/30 text-emerald-200 backdrop-blur-xs mb-8">
            <Building2 size={13} className="text-emerald-300" />
            <span>Manufacturing & Sales Management</span>
          </div>

          <h1 className="text-4xl xl:text-5xl font-black tracking-tight text-white leading-tight">
            Business Management System
          </h1>
          <p className="mt-3 text-lg font-medium text-emerald-200/90 tracking-wide">
            One System. Every Operation.
          </p>
        </div>

        {/* Middle: Manufacturing & Operations Pillars */}
        <div className="my-10 space-y-4 relative z-10">
          <div className="flex items-start gap-3.5 p-3.5 rounded-xl bg-white/5 border border-white/10 backdrop-blur-xs">
            <div className="w-9 h-9 rounded-lg bg-emerald-800/80 flex items-center justify-center text-emerald-200 shrink-0 mt-0.5">
              <Factory size={18} />
            </div>
            <div>
              <h2 className="text-sm font-bold text-white m-0">Factory & Milling Operations</h2>
              <p className="text-xs text-emerald-100/70 mt-0.5 leading-relaxed m-0">
                Moong & chana milling, automated recipe BOMs, packaging batches, and floor attendance.
              </p>
            </div>
          </div>

          <div className="flex items-start gap-3.5 p-3.5 rounded-xl bg-white/5 border border-white/10 backdrop-blur-xs">
            <div className="w-9 h-9 rounded-lg bg-emerald-800/80 flex items-center justify-center text-emerald-200 shrink-0 mt-0.5">
              <Truck size={18} />
            </div>
            <div>
              <h2 className="text-sm font-bold text-white m-0">Field Sales & Van Inventory</h2>
              <p className="text-xs text-emerald-100/70 mt-0.5 leading-relaxed m-0">
                Live shopkeeper invoicing, van packet stock balances, and instant cash collections.
              </p>
            </div>
          </div>

          <div className="flex items-start gap-3.5 p-3.5 rounded-xl bg-white/5 border border-white/10 backdrop-blur-xs">
            <div className="w-9 h-9 rounded-lg bg-emerald-800/80 flex items-center justify-center text-emerald-200 shrink-0 mt-0.5">
              <Scale size={18} />
            </div>
            <div>
              <h2 className="text-sm font-bold text-white m-0">Double-Entry Financial Ledgers</h2>
              <p className="text-xs text-emerald-100/70 mt-0.5 leading-relaxed m-0">
                Balanced trial balance, customer receivables, supplier payables, and daily closings.
              </p>
            </div>
          </div>
        </div>

        {/* Bottom: Heritage & System Health */}
        <div className="pt-6 border-t border-emerald-800/60 flex items-center justify-between text-xs text-emerald-300/80 relative z-10">
          <div>
            <span className="font-semibold text-emerald-200 block">Kawad Swad Udhyog</span>
            <span className="text-[11px] text-emerald-400/80">Nimar Region, Madhya Pradesh · Est. 1998</span>
          </div>

          <div className="inline-flex items-center gap-2 px-2.5 py-1 rounded-md bg-emerald-950/80 border border-emerald-800/50 text-[11px] font-medium text-emerald-300">
            <span className={`w-2 h-2 rounded-full ${connState.dot}`} />
            <span>{connState.label}</span>
          </div>
        </div>
      </div>

      {/* ------------------------------------------------------------------ */}
      {/* RIGHT SECTION: CLEAN & MODERN LOGIN FORM                           */}
      {/* ------------------------------------------------------------------ */}
      <div className="flex-1 flex flex-col justify-center items-center p-6 sm:p-10 lg:p-16">
        {/* Mobile Header Branding (Visible on mobile/tablet only) */}
        <div className="lg:hidden w-full max-w-md text-center mb-6">
          <div className="inline-flex items-center justify-center w-12 h-12 rounded-xl bg-emerald-800 text-white font-black text-xl mb-2.5 shadow-md border border-amber-200/30">
            KS
          </div>
          <h2 className="text-xl font-black text-slate-900 tracking-tight m-0">
            Kawad Swad Udhyog
          </h2>
          <p className="text-xs text-emerald-800 font-semibold mt-0.5 m-0">
            Business Management System
          </p>
          <p className="text-xs text-slate-500 mt-1 m-0">
            One System. Every Operation.
          </p>
        </div>

        {/* Main Login Card */}
        <div className="w-full max-w-md bg-white border border-slate-200/90 rounded-2xl shadow-xl shadow-slate-200/50 p-7 sm:p-9 relative">
          {/* Card Title & Instructions */}
          <div className="mb-6">
            <div className="flex items-center justify-between">
              <h2 className="text-xl font-bold text-slate-900 tracking-tight m-0">
                Sign In to ERP
              </h2>
              <span className="inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-full text-[11px] font-bold bg-emerald-50 text-emerald-800 border border-emerald-200">
                <ShieldCheck size={13} className="text-emerald-700" />
                Staff Portal
              </span>
            </div>
            <p className="text-xs text-slate-500 mt-1.5 leading-relaxed m-0">
              Enter your staff credentials to access your daily operational workspace.
            </p>
          </div>

          {/* Form */}
          <form onSubmit={handleSubmit} className="space-y-4">
            {/* Username / User ID Field */}
            <div>
              <label
                className="block text-xs font-bold uppercase tracking-wider text-slate-700 mb-1.5"
                htmlFor="login-username"
              >
                User ID / Username
              </label>
              <div className="relative">
                <span className="absolute inset-y-0 left-0 flex items-center pl-3.5 text-slate-400 pointer-events-none">
                  <User size={17} />
                </span>
                <input
                  id="login-username"
                  type="text"
                  value={username}
                  onChange={(e) => {
                    setUsername(e.target.value);
                    if (error) setError(null);
                  }}
                  autoComplete="username"
                  required
                  placeholder="e.g. owner, sales_ramesh, factory_lead"
                  disabled={isLoading}
                  className="w-full pl-10 pr-3 py-2.5 text-sm bg-white border border-slate-300 rounded-xl focus:outline-hidden focus:ring-2 focus:ring-emerald-800 focus:border-emerald-800 transition-colors disabled:bg-slate-50 disabled:text-slate-500 font-medium placeholder:text-slate-400"
                />
              </div>
            </div>

            {/* Password Field */}
            <div>
              <label
                className="block text-xs font-bold uppercase tracking-wider text-slate-700 mb-1.5"
                htmlFor="login-password"
              >
                Password
              </label>
              <div className="relative">
                <span className="absolute inset-y-0 left-0 flex items-center pl-3.5 text-slate-400 pointer-events-none">
                  <Lock size={17} />
                </span>
                <input
                  id="login-password"
                  type={showPassword ? 'text' : 'password'}
                  value={password}
                  onChange={(e) => {
                    setPassword(e.target.value);
                    if (error) setError(null);
                  }}
                  autoComplete="current-password"
                  required
                  placeholder="Enter your password"
                  disabled={isLoading}
                  className="w-full pl-10 pr-11 py-2.5 text-sm bg-white border border-slate-300 rounded-xl focus:outline-hidden focus:ring-2 focus:ring-emerald-800 focus:border-emerald-800 transition-colors disabled:bg-slate-50 disabled:text-slate-500 font-medium placeholder:text-slate-400"
                />
                <button
                  type="button"
                  onClick={() => setShowPassword(!showPassword)}
                  className="absolute inset-y-0 right-0 flex items-center pr-3.5 text-slate-400 hover:text-slate-700 transition-colors cursor-pointer"
                  tabIndex={-1}
                  aria-label={showPassword ? 'Hide password' : 'Show password'}
                >
                  {showPassword ? <EyeOff size={17} /> : <Eye size={17} />}
                </button>
              </div>
            </div>

            {/* Remember Username Option */}
            <div className="flex items-center justify-between pt-1">
              <label className="flex items-center gap-2 cursor-pointer text-xs font-medium text-slate-600 select-none">
                <input
                  type="checkbox"
                  checked={rememberUser}
                  onChange={(e) => {
                    const isChecked = e.target.checked;
                    setRememberUser(isChecked);
                    if (!isChecked && typeof window !== 'undefined') {
                      try {
                        localStorage.removeItem(REMEMBERED_USER_KEY);
                      } catch {
                        // ignore
                      }
                    }
                  }}
                  disabled={isLoading}
                  className="w-4 h-4 rounded text-emerald-800 focus:ring-emerald-700 border-slate-300 cursor-pointer"
                />
                <span>Remember User ID on this device</span>
              </label>
            </div>

            {/* Error Message Alert */}
            {error && (
              <div
                className={`p-3.5 rounded-xl text-xs space-y-1 border ${
                  error.type === 'auth'
                    ? 'bg-rose-50 border-rose-200 text-rose-900'
                    : error.type === 'network'
                    ? 'bg-amber-50 border-amber-200 text-amber-900'
                    : 'bg-slate-50 border-slate-300 text-slate-800'
                }`}
              >
                <div className="flex items-center gap-1.5 font-bold">
                  <AlertCircle
                    size={15}
                    className={error.type === 'auth' ? 'text-rose-600' : 'text-amber-600'}
                  />
                  <span>
                    {error.type === 'auth'
                      ? 'Authentication Failed'
                      : error.type === 'network'
                      ? 'Connection Notice'
                      : 'Access Restricted'}
                  </span>
                </div>
                <p className="m-0 leading-relaxed font-medium">{error.message}</p>
              </div>
            )}

            {/* Submit Action Button */}
            <button
              type="submit"
              disabled={isLoading}
              className="w-full py-3 px-4 rounded-xl bg-emerald-800 hover:bg-emerald-900 active:bg-emerald-950 text-white font-bold text-sm shadow-sm transition-all flex items-center justify-center gap-2 cursor-pointer disabled:opacity-60 disabled:cursor-not-allowed mt-2"
            >
              {isLoading ? (
                <>
                  <RefreshCw size={16} className="animate-spin text-white" />
                  <span>Signing In…</span>
                </>
              ) : (
                <span>Sign In to ERP</span>
              )}
            </button>
          </form>

          {/* Footer Controls: Live Connection State & Optional Server Config */}
          <div className="mt-6 pt-4 border-t border-slate-100 flex items-center justify-between text-xs">
            <div className="flex items-center gap-1.5">
              <span className={`w-2 h-2 rounded-full ${connState.dot}`} />
              <span className="text-[11px] font-medium text-slate-500">
                {connState.label}
              </span>
            </div>

            <button
              type="button"
              onClick={() => setShowServerConfig(!showServerConfig)}
              className="inline-flex items-center gap-1 text-slate-400 hover:text-slate-700 text-[11px] font-medium transition-colors cursor-pointer"
              title="Configure Backend Server Endpoint"
            >
              <Settings size={12} />
              <span>{showServerConfig ? 'Close' : 'Server Config'}</span>
            </button>
          </div>

          {/* Collapsible Server Configuration Panel */}
          {showServerConfig && (
            <form
              onSubmit={handleSaveBackendUrl}
              className="mt-3 p-3.5 bg-slate-50 border border-slate-200 rounded-xl space-y-2 text-left text-xs"
            >
              <label className="block text-[11px] font-bold text-slate-700" htmlFor="endpoint-url">
                Backend Server Endpoint URL
              </label>
              <input
                id="endpoint-url"
                type="url"
                value={customUrl}
                onChange={(e) => setCustomUrl(e.target.value)}
                placeholder="https://kawad-swad-sales-dev.onrender.com"
                required
                className="w-full px-2.5 py-1.5 text-xs bg-white border border-slate-300 rounded-lg focus:outline-hidden focus:ring-1 focus:ring-emerald-700 font-mono"
              />
              <div className="flex items-center gap-2 pt-1">
                <button
                  type="submit"
                  className="px-3 py-1 bg-emerald-800 hover:bg-emerald-900 text-white text-xs font-semibold rounded-lg transition-colors cursor-pointer"
                >
                  Apply URL
                </button>
                <button
                  type="button"
                  onClick={() => {
                    setCustomUrl('https://kawad-swad-sales-dev.onrender.com');
                    updateBackendUrl('https://kawad-swad-sales-dev.onrender.com');
                    setShowServerConfig(false);
                  }}
                  className="px-3 py-1 bg-white border border-slate-300 hover:bg-slate-50 text-slate-700 text-xs font-semibold rounded-lg transition-colors cursor-pointer"
                >
                  Reset Default
                </button>
              </div>
            </form>
          )}
        </div>

        {/* Security & Access Notice */}
        <p className="mt-6 text-center text-xs text-slate-400 font-medium max-w-sm leading-relaxed">
          Authorized personnel only. All access, billing transactions, and inventory operations are audited and logged.
        </p>
      </div>
    </div>
  );
};
