import React, { useState } from 'react';
import { useStore } from '../context/StoreContext';
import {
  Lock,
  User,
  AlertCircle,
  RefreshCw,
  Eye,
  EyeOff,
  Server,
  Settings,
  CheckCircle2,
} from 'lucide-react';

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
  const [showPassword, setShowPassword] = useState(false);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<{ message: string; type: 'auth' | 'network' | 'forbidden' } | null>(null);
  const [showServerConfig, setShowServerConfig] = useState(false);
  const [customUrl, setCustomUrl] = useState(backendUrl);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (isLoading) return;
    setError(null);

    const cleanUser = username.trim();
    if (!cleanUser || !password) {
      setError({
        message: 'Please enter both username and password.',
        type: 'auth',
      });
      return;
    }

    setIsLoading(true);
    try {
      await login(cleanUser, password);
    } catch (err: unknown) {
      const rawMsg = err instanceof Error ? err.message : String(err);
      const lower = rawMsg.toLowerCase();

      if (lower.includes('401') || lower.includes('invalid') || lower.includes('unauthorized') || lower.includes('credentials')) {
        setError({
          message: 'Username or password is incorrect. Please verify your credentials.',
          type: 'auth',
        });
      } else if (lower.includes('403') || lower.includes('deactivated') || lower.includes('legacy')) {
        setError({
          message: rawMsg.replace(/HTTP \d+:\s*/i, ''),
          type: 'forbidden',
        });
      } else if (lower.includes('429') || lower.includes('quota') || lower.includes('too many')) {
        setError({
          message: 'Too many login attempts or server quota exceeded. Please wait a moment and try again.',
          type: 'network',
        });
      } else if (lower.includes('503') || lower.includes('failed to fetch') || lower.includes('network') || lower.includes('timeout') || lower.includes('offline') || lower.includes('standby')) {
        setError({
          message: 'The ERP server is temporarily unavailable or waking up from standby. Please retry in a few moments.',
          type: 'network',
        });
      } else {
        setError({
          message: rawMsg || 'Login failed. Please check your connection and try again.',
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

  return (
    <div className="min-h-[calc(100vh-64px)] flex items-center justify-center p-4 bg-slate-50/70 py-10">
      <div className="w-full max-w-md bg-white border border-slate-200 rounded-2xl shadow-xl overflow-hidden">
        {/* Brand Header */}
        <div className="p-6 sm:p-8 bg-gradient-to-b from-slate-900 to-slate-800 text-white text-center relative">
          <div className="inline-flex items-center justify-center w-14 h-14 rounded-2xl bg-emerald-600 text-white font-extrabold text-2xl mb-3 shadow-md border border-emerald-400/30">
            KS
          </div>
          <h1 className="text-2xl font-black tracking-tight text-white m-0">
            Kawad Swad Udhyog
          </h1>
          <p className="text-xs text-slate-300 font-medium mt-1">
            Manufacturing & Sales Management ERP · Nimar, MP
          </p>

          {/* Connection Status Indicator */}
          <div className="mt-4 inline-flex items-center gap-2 px-3 py-1 rounded-full text-xs font-semibold bg-white/10 backdrop-blur-md border border-white/15">
            <span
              className={`w-2 h-2 rounded-full ${
                isGoogleSheetsConnected && persistentWritesEnabled
                  ? 'bg-emerald-400'
                  : isBackendConnected
                  ? 'bg-amber-400 animate-pulse'
                  : 'bg-rose-400'
              }`}
            />
            <span>
              {isGoogleSheetsConnected && persistentWritesEnabled
                ? 'ERP Connected · Persistent Storage Verified'
                : isBackendConnected
                ? 'API Online · Storage Not Verified'
                : 'API Offline · Check Server Connection'}
            </span>
          </div>
        </div>

        {/* Focused Sign-In Form */}
        <div className="p-6 sm:p-8 space-y-5">
          <form onSubmit={handleSubmit} className="space-y-4">
            <div>
              <label
                className="block text-xs font-bold uppercase tracking-wider text-slate-700 mb-1.5"
                htmlFor="login-username"
              >
                Username
              </label>
              <div className="relative">
                <span className="absolute inset-y-0 left-0 flex items-center pl-3.5 text-slate-400 pointer-events-none">
                  <User size={16} />
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
                  placeholder="Enter your username"
                  disabled={isLoading}
                  className="w-full pl-10 pr-3 py-2.5 text-sm bg-white border border-slate-300 rounded-lg focus:outline-hidden focus:ring-2 focus:ring-emerald-700 focus:border-emerald-700 transition-colors disabled:bg-slate-50 disabled:text-slate-500 font-medium"
                />
              </div>
            </div>

            <div>
              <label
                className="block text-xs font-bold uppercase tracking-wider text-slate-700 mb-1.5"
                htmlFor="login-password"
              >
                Password
              </label>
              <div className="relative">
                <span className="absolute inset-y-0 left-0 flex items-center pl-3.5 text-slate-400 pointer-events-none">
                  <Lock size={16} />
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
                  className="w-full pl-10 pr-11 py-2.5 text-sm bg-white border border-slate-300 rounded-lg focus:outline-hidden focus:ring-2 focus:ring-emerald-700 focus:border-emerald-700 transition-colors disabled:bg-slate-50 disabled:text-slate-500 font-medium"
                />
                <button
                  type="button"
                  onClick={() => setShowPassword(!showPassword)}
                  className="absolute inset-y-0 right-0 flex items-center pr-3.5 text-slate-400 hover:text-slate-700 transition-colors cursor-pointer"
                  tabIndex={-1}
                  aria-label={showPassword ? 'Hide password' : 'Show password'}
                >
                  {showPassword ? <EyeOff size={16} /> : <Eye size={16} />}
                </button>
              </div>
            </div>

            {/* Error Message Box */}
            {error && (
              <div
                className={`p-3.5 rounded-lg text-xs space-y-1 border ${
                  error.type === 'auth'
                    ? 'bg-red-50 border-red-200 text-red-800'
                    : error.type === 'network'
                    ? 'bg-amber-50 border-amber-200 text-amber-900'
                    : 'bg-slate-50 border-slate-300 text-slate-800'
                }`}
              >
                <div className="flex items-center gap-1.5 font-bold">
                  <AlertCircle size={15} className={error.type === 'auth' ? 'text-red-600' : 'text-amber-600'} />
                  <span>
                    {error.type === 'auth'
                      ? 'Authentication Failed'
                      : error.type === 'network'
                      ? 'Connection Notice'
                      : 'Access Restricted'}
                  </span>
                </div>
                <p className="m-0 leading-relaxed">{error.message}</p>
              </div>
            )}

            {/* Submit Button */}
            <button
              type="submit"
              disabled={isLoading}
              className="w-full py-3 px-4 rounded-lg bg-emerald-800 hover:bg-emerald-900 active:bg-emerald-950 text-white font-bold text-sm shadow-sm transition-colors flex items-center justify-center gap-2 cursor-pointer disabled:opacity-60 disabled:cursor-not-allowed"
            >
              {isLoading ? (
                <>
                  <RefreshCw size={16} className="animate-spin" />
                  <span>Authenticating…</span>
                </>
              ) : (
                <span>Sign In to ERP</span>
              )}
            </button>
          </form>

          {/* Connection Status & Optional Server Settings */}
          <div className="pt-3 border-t border-slate-100 flex items-center justify-between text-xs text-slate-500">
            <div className="flex items-center gap-1.5">
              <span
                className={`w-2 h-2 rounded-full ${
                  isBackendConnected && isGoogleSheetsConnected && persistentWritesEnabled
                    ? 'bg-emerald-500'
                    : isBackendConnected
                    ? 'bg-amber-400'
                    : 'bg-rose-500'
                }`}
              />
              <span className="text-[11px] font-medium text-slate-600">
                {isBackendConnected ? 'Backend API Reachable' : 'Backend API Offline'}
              </span>
            </div>

            <button
              type="button"
              onClick={() => setShowServerConfig(!showServerConfig)}
              className="inline-flex items-center gap-1 text-slate-400 hover:text-slate-700 text-[11px] font-medium transition-colors cursor-pointer"
            >
              <Settings size={12} />
              <span>{showServerConfig ? 'Hide' : 'Server Config'}</span>
            </button>
          </div>

          {/* Collapsible Server Configuration Panel */}
          {showServerConfig && (
            <form
              onSubmit={handleSaveBackendUrl}
              className="p-3 bg-slate-50 border border-slate-200 rounded-lg space-y-2 text-left text-xs"
            >
              <label className="block text-[11px] font-bold text-slate-700" htmlFor="endpoint-url">
                Backend Server URL
              </label>
              <input
                id="endpoint-url"
                type="url"
                value={customUrl}
                onChange={(e) => setCustomUrl(e.target.value)}
                placeholder="https://kawad-swad-sales-dev.onrender.com"
                required
                className="w-full px-2.5 py-1.5 text-xs bg-white border border-slate-300 rounded-md focus:outline-hidden focus:ring-1 focus:ring-emerald-700"
              />
              <div className="flex items-center gap-2 pt-1">
                <button
                  type="submit"
                  className="px-3 py-1 bg-emerald-800 hover:bg-emerald-900 text-white text-xs font-semibold rounded-md transition-colors cursor-pointer"
                >
                  Save URL
                </button>
                <button
                  type="button"
                  onClick={() => {
                    setCustomUrl('https://kawad-swad-sales-dev.onrender.com');
                    updateBackendUrl('https://kawad-swad-sales-dev.onrender.com');
                    setShowServerConfig(false);
                  }}
                  className="px-3 py-1 bg-white border border-slate-300 hover:bg-slate-50 text-slate-700 text-xs font-semibold rounded-md transition-colors cursor-pointer"
                >
                  Reset Default
                </button>
              </div>
            </form>
          )}
        </div>
      </div>
    </div>
  );
};
