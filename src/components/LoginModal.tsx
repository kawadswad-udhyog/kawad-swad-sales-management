import React, { useState } from 'react';
import { useStore } from '../context/StoreContext';
import {
  Lock,
  User,
  AlertCircle,
  RefreshCw,
  Settings,
  Eye,
  EyeOff,
  Shield,
  Briefcase,
  Truck,
  CheckCircle2,
} from 'lucide-react';

export const LoginModal: React.FC = () => {
  const { login, backendUrl, updateBackendUrl, isBackendConnected, connectionError } = useStore();
  const [username, setUsername] = useState('owner');
  const [password, setPassword] = useState('kawad123');
  const [showPassword, setShowPassword] = useState(false);
  const [isLoading, setIsLoading] = useState(false);
  const [activeRoleLoggingIn, setActiveRoleLoggingIn] = useState<string | null>(null);
  const [error, setError] = useState('');
  const [showServerConfig, setShowServerConfig] = useState(false);
  const [customUrl, setCustomUrl] = useState(backendUrl);

  const performLogin = async (u: string, p: string) => {
    if (isLoading) return;
    setError('');

    if (!u.trim() || !p) {
      setError('Please enter both username and password.');
      return;
    }

    setIsLoading(true);
    try {
      await login(u.trim(), p);
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : 'Login failed. Please verify credentials.';
      setError(msg);
    } finally {
      setIsLoading(false);
      setActiveRoleLoggingIn(null);
    }
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    await performLogin(username, password);
  };

  const handleQuickRoleLogin = async (roleUsername: string, defaultPass: string) => {
    setUsername(roleUsername);
    setPassword(defaultPass);
    setActiveRoleLoggingIn(roleUsername);
    await performLogin(roleUsername, defaultPass);
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
      <div className="w-full max-w-lg bg-white border border-slate-200 rounded-2xl shadow-xl p-6 sm:p-8 space-y-6">
        {/* Brand Header */}
        <div className="text-center pb-5 border-b border-slate-100">
          <div className="inline-flex items-center justify-center w-14 h-14 rounded-2xl bg-emerald-800 text-white font-extrabold text-xl mb-3 shadow-sm tracking-tight">
            KS
          </div>
          <h1 className="text-2xl font-extrabold text-slate-900 tracking-tight m-0">
            Kawad Swad Udhyog
          </h1>
          <p className="text-xs text-slate-500 font-medium mt-1">
            Sales & Factory Management Enterprise ERP · Nimar, MP
          </p>
        </div>

        {/* Quick Role Login Buttons */}
        <div>
          <div className="flex items-center justify-between mb-2.5">
            <span className="text-[11px] font-bold uppercase tracking-wider text-slate-500">
              1-Click Fast Workspace Access
            </span>
            <span className="text-[10px] text-emerald-800 font-bold bg-emerald-50 px-2 py-0.5 rounded-md border border-emerald-200">
              Instant Session
            </span>
          </div>

          <div className="grid grid-cols-3 gap-2.5">
            <button
              type="button"
              disabled={isLoading}
              onClick={() => handleQuickRoleLogin('owner', 'kawad123')}
              className={`flex flex-col items-center justify-center p-3 rounded-xl border text-center transition-all cursor-pointer ${
                activeRoleLoggingIn === 'owner'
                  ? 'border-emerald-600 bg-emerald-50 text-emerald-900 ring-2 ring-emerald-600'
                  : 'border-slate-200 hover:border-emerald-400 hover:bg-slate-50 text-slate-700'
              }`}
            >
              <div className="w-8 h-8 rounded-lg bg-amber-100 text-amber-800 flex items-center justify-center mb-1.5 shrink-0">
                <Shield size={16} />
              </div>
              <strong className="text-xs font-bold leading-tight">Admin/Owner</strong>
              <small className="text-[10px] text-slate-500 mt-0.5">Full ERP Access</small>
            </button>

            <button
              type="button"
              disabled={isLoading}
              onClick={() => handleQuickRoleLogin('mahi', 'kawad123')}
              className={`flex flex-col items-center justify-center p-3 rounded-xl border text-center transition-all cursor-pointer ${
                activeRoleLoggingIn === 'mahi'
                  ? 'border-emerald-600 bg-emerald-50 text-emerald-900 ring-2 ring-emerald-600'
                  : 'border-slate-200 hover:border-emerald-400 hover:bg-slate-50 text-slate-700'
              }`}
            >
              <div className="w-8 h-8 rounded-lg bg-blue-100 text-blue-800 flex items-center justify-center mb-1.5 shrink-0">
                <Briefcase size={16} />
              </div>
              <strong className="text-xs font-bold leading-tight">Assistant PA</strong>
              <small className="text-[10px] text-slate-500 mt-0.5">Floor & Ledgers</small>
            </button>

            <button
              type="button"
              disabled={isLoading}
              onClick={() => handleQuickRoleLogin('salesman', 'kawad123')}
              className={`flex flex-col items-center justify-center p-3 rounded-xl border text-center transition-all cursor-pointer ${
                activeRoleLoggingIn === 'salesman'
                  ? 'border-emerald-600 bg-emerald-50 text-emerald-900 ring-2 ring-emerald-600'
                  : 'border-slate-200 hover:border-emerald-400 hover:bg-slate-50 text-slate-700'
              }`}
            >
              <div className="w-8 h-8 rounded-lg bg-emerald-100 text-emerald-800 flex items-center justify-center mb-1.5 shrink-0">
                <Truck size={16} />
              </div>
              <strong className="text-xs font-bold leading-tight">Field Sales</strong>
              <small className="text-[10px] text-slate-500 mt-0.5">Orders & Cash</small>
            </button>
          </div>
        </div>

        {/* Divider */}
        <div className="relative flex py-1 items-center">
          <div className="flex-grow border-t border-slate-200"></div>
          <span className="flex-shrink mx-3 text-[11px] text-slate-400 uppercase font-semibold">
            Or sign in with custom credentials
          </span>
          <div className="flex-grow border-t border-slate-200"></div>
        </div>

        {/* Main Credentials Form */}
        <form onSubmit={handleSubmit} className="space-y-4">
          <div>
            <label className="block text-xs font-semibold text-slate-700 mb-1" htmlFor="login-username">
              Username
            </label>
            <div className="relative">
              <span className="absolute inset-y-0 left-0 flex items-center pl-3 text-slate-400 pointer-events-none">
                <User size={16} />
              </span>
              <input
                id="login-username"
                type="text"
                value={username}
                onChange={(e) => setUsername(e.target.value)}
                autoComplete="username"
                required
                placeholder="e.g. owner, mahi, or salesman"
                disabled={isLoading}
                className="w-full pl-9 pr-3 py-2 text-sm bg-white border border-slate-300 rounded-lg focus:outline-hidden focus:ring-2 focus:ring-emerald-700 focus:border-emerald-700 transition-colors disabled:bg-slate-50 disabled:text-slate-500"
              />
            </div>
          </div>

          <div>
            <label className="block text-xs font-semibold text-slate-700 mb-1" htmlFor="login-password">
              Password
            </label>
            <div className="relative">
              <span className="absolute inset-y-0 left-0 flex items-center pl-3 text-slate-400 pointer-events-none">
                <Lock size={16} />
              </span>
              <input
                id="login-password"
                type={showPassword ? 'text' : 'password'}
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                autoComplete="current-password"
                required
                placeholder="Account password"
                disabled={isLoading}
                className="w-full pl-9 pr-10 py-2 text-sm bg-white border border-slate-300 rounded-lg focus:outline-hidden focus:ring-2 focus:ring-emerald-700 focus:border-emerald-700 transition-colors disabled:bg-slate-50 disabled:text-slate-500"
              />
              <button
                type="button"
                onClick={() => setShowPassword(!showPassword)}
                className="absolute inset-y-0 right-0 flex items-center pr-3 text-slate-400 hover:text-slate-600 transition-colors cursor-pointer"
                tabIndex={-1}
              >
                {showPassword ? <EyeOff size={16} /> : <Eye size={16} />}
              </button>
            </div>
          </div>

          {/* Error Message Box */}
          {error && (
            <div className="p-3 bg-red-50 border border-red-200 rounded-lg text-xs text-red-800 space-y-1">
              <div className="flex items-center gap-1.5 font-bold">
                <AlertCircle size={14} className="text-red-600" />
                <span>Authentication Notice</span>
              </div>
              <p className="text-red-700 m-0">{error}</p>
            </div>
          )}

          {/* Submit Button */}
          <button
            type="submit"
            disabled={isLoading}
            className="w-full py-2.5 px-4 rounded-lg bg-emerald-800 hover:bg-emerald-900 active:bg-emerald-950 text-white font-semibold text-sm shadow-xs transition-colors flex items-center justify-center gap-2 cursor-pointer disabled:opacity-60 disabled:cursor-not-allowed"
          >
            {isLoading ? (
              <>
                <RefreshCw size={16} className="animate-spin" />
                <span>Signing in to ERP…</span>
              </>
            ) : (
              <span>Sign In</span>
            )}
          </button>
        </form>

        {/* Server Connection Indicator & Drawer */}
        <div className="pt-4 border-t border-slate-100 flex items-center justify-between text-xs text-slate-500">
          <div className="flex items-center gap-1.5">
            <span
              className={`w-2 h-2 rounded-full ${
                isBackendConnected ? 'bg-emerald-500' : 'bg-amber-500 animate-pulse'
              }`}
            />
            <span>{isBackendConnected ? 'FastAPI Backend Online' : 'Local Fallback / Standby'}</span>
          </div>

          <button
            type="button"
            onClick={() => setShowServerConfig(!showServerConfig)}
            className="inline-flex items-center gap-1 text-slate-500 hover:text-slate-800 font-medium transition-colors cursor-pointer"
          >
            <Settings size={13} />
            <span>{showServerConfig ? 'Close' : 'Backend URL'}</span>
          </button>
        </div>

        {/* Server Configuration Panel */}
        {showServerConfig && (
          <form
            onSubmit={handleSaveBackendUrl}
            className="p-3.5 bg-slate-50 border border-slate-200 rounded-lg space-y-2.5 text-left text-xs"
          >
            <label className="block text-[11px] font-semibold text-slate-700" htmlFor="endpoint-url">
              FastAPI Endpoint URL (Render Web Service)
            </label>
            <input
              id="endpoint-url"
              type="url"
              value={customUrl}
              onChange={(e) => setCustomUrl(e.target.value)}
              placeholder="https://kawad-swad-sales-backend.onrender.com"
              required
              className="w-full px-3 py-1.5 text-xs bg-white border border-slate-300 rounded-md focus:outline-hidden focus:ring-1 focus:ring-emerald-700"
            />
            <div className="flex items-center gap-2 pt-1">
              <button
                type="submit"
                className="px-3 py-1 bg-emerald-800 hover:bg-emerald-900 text-white text-xs font-semibold rounded-md transition-colors cursor-pointer"
              >
                Save
              </button>
              <button
                type="button"
                onClick={() => {
                  setCustomUrl('https://kawad-swad-sales-backend.onrender.com');
                  updateBackendUrl('https://kawad-swad-sales-backend.onrender.com');
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
  );
};
