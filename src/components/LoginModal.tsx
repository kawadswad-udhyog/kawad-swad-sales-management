import React, { useState, useEffect } from 'react';
import { useStore } from '../context/StoreContext';
import { getApiDebugLogs, clearApiDebugLogs, ApiLogEntry } from '../services/api';
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
  Database,
  Copy,
  Check,
  ExternalLink,
  FileSpreadsheet,
  HelpCircle,
  Sparkles,
  ChevronRight,
  Server,
} from 'lucide-react';

export const LoginModal: React.FC = () => {
  const {
    login,
    backendUrl,
    updateBackendUrl,
    isBackendConnected,
    isGoogleSheetsConnected,
    persistentWritesEnabled,
    connectionError,
    reconnectGoogleSheets,
    verifyGoogleSheetsTabs,
    bootstrapOwnerAccount,
  } = useStore();

  const [activeTab, setActiveTab] = useState<'signin' | 'sheets_guide'>('signin');
  const [username, setUsername] = useState('owner');
  const [password, setPassword] = useState('kawad123');
  const [showPassword, setShowPassword] = useState(false);
  const [isLoading, setIsLoading] = useState(false);
  const [activeRoleLoggingIn, setActiveRoleLoggingIn] = useState<string | null>(null);
  const [error, setError] = useState('');
  const [showServerConfig, setShowServerConfig] = useState(false);
  const [customUrl, setCustomUrl] = useState(backendUrl);

  // Sheets Setup Guide States
  const [sheetUrlInput, setSheetUrlInput] = useState('');
  const [extractedSheetId, setExtractedSheetId] = useState('');
  const [copiedKey, setCopiedKey] = useState<string | null>(null);
  const [isReconnecting, setIsReconnecting] = useState(false);
  const [reconnectResult, setReconnectResult] = useState<{ success: boolean; message: string } | null>(null);
  const [isVerifyingTabs, setIsVerifyingTabs] = useState(false);
  const [verifyResult, setVerifyResult] = useState<any>(null);

  // Bootstrap owner modal state
  const [showBootstrapForm, setShowBootstrapForm] = useState(false);
  const [bootstrapUsername, setBootstrapUsername] = useState('ankit');
  const [bootstrapPassword, setBootstrapPassword] = useState('');
  const [bootstrapFullName, setBootstrapFullName] = useState('Ankit Mandloi');
  const [isBootstrapping, setIsBootstrapping] = useState(false);
  const [bootstrapStatus, setBootstrapStatus] = useState<{ success: boolean; message: string } | null>(null);

  // Live Connection Diagnostics
  const [debugLogs, setDebugLogs] = useState<ApiLogEntry[]>([]);

  useEffect(() => {
    if (showServerConfig || activeTab === 'sheets_guide') {
      setDebugLogs(getApiDebugLogs());
      const timer = setInterval(() => {
        setDebugLogs(getApiDebugLogs());
      }, 2500);
      return () => clearInterval(timer);
    }
  }, [showServerConfig, activeTab]);

  const extractSheetId = (input: string) => {
    setSheetUrlInput(input);
    const trimmed = input.trim();
    // Pattern: /d/([a-zA-Z0-9-_]+)
    const match = trimmed.match(/\/d\/([a-zA-Z0-9-_]+)/);
    if (match && match[1]) {
      setExtractedSheetId(match[1]);
    } else if (trimmed.length > 20 && !trimmed.includes('/')) {
      setExtractedSheetId(trimmed);
    } else {
      setExtractedSheetId('');
    }
  };

  const copyToClipboard = (text: string, keyName: string) => {
    navigator.clipboard.writeText(text);
    setCopiedKey(keyName);
    setTimeout(() => setCopiedKey(null), 2500);
  };

  const handleTestReconnect = async () => {
    setIsReconnecting(true);
    setReconnectResult(null);
    try {
      const res = await reconnectGoogleSheets();
      setReconnectResult(res);
    } finally {
      setIsReconnecting(false);
    }
  };

  const handleVerifyTabs = async () => {
    setIsVerifyingTabs(true);
    setVerifyResult(null);
    try {
      const res = await verifyGoogleSheetsTabs();
      setVerifyResult(res);
    } finally {
      setIsVerifyingTabs(false);
    }
  };

  const handleBootstrapOwner = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!bootstrapUsername || bootstrapPassword.length < 6) {
      setBootstrapStatus({ success: false, message: 'Password must be at least 6 characters.' });
      return;
    }
    setIsBootstrapping(true);
    setBootstrapStatus(null);
    try {
      const res = await bootstrapOwnerAccount(bootstrapUsername, bootstrapPassword, bootstrapFullName);
      setBootstrapStatus(res);
      if (res.success) {
        setUsername(bootstrapUsername);
        setPassword(bootstrapPassword);
      }
    } finally {
      setIsBootstrapping(false);
    }
  };

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
    setError('');
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
      <div className="w-full max-w-xl bg-white border border-slate-200 rounded-2xl shadow-xl overflow-hidden">
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

          {/* Connection Status Pill Banner */}
          <div className="mt-4 inline-flex items-center gap-2 px-3 py-1 rounded-full text-xs font-semibold bg-white/10 backdrop-blur-md border border-white/15">
            <span
              className={`w-2 h-2 rounded-full ${
                isGoogleSheetsConnected && persistentWritesEnabled
                  ? 'bg-emerald-400'
                  : isBackendConnected
                  ? 'bg-amber-400 animate-pulse'
                  : 'bg-red-400'
              }`}
            />
            <span>
              {isGoogleSheetsConnected && persistentWritesEnabled
                ? 'Production Online · Google Sheets Connected'
                : isBackendConnected
                ? 'FastAPI Online · Google Sheets Standby'
                : 'Local Standby Mode Active · ERP Ready to Use'}
            </span>
          </div>
        </div>

        {/* Tab Switcher */}
        <div className="flex border-b border-slate-200 bg-slate-100/70 text-xs font-bold text-slate-600">
          <button
            type="button"
            onClick={() => setActiveTab('signin')}
            className={`flex-1 py-3 px-4 flex items-center justify-center gap-2 transition-colors cursor-pointer ${
              activeTab === 'signin'
                ? 'bg-white text-emerald-800 border-b-2 border-emerald-700 font-extrabold'
                : 'hover:text-slate-900 hover:bg-slate-50'
            }`}
          >
            <Lock size={15} />
            <span>Sign In to ERP</span>
          </button>
          <button
            type="button"
            onClick={() => setActiveTab('sheets_guide')}
            className={`flex-1 py-3 px-4 flex items-center justify-center gap-2 transition-colors cursor-pointer ${
              activeTab === 'sheets_guide'
                ? 'bg-white text-emerald-800 border-b-2 border-emerald-700 font-extrabold'
                : 'hover:text-slate-900 hover:bg-slate-50'
            }`}
          >
            <Database size={15} />
            <span>🚀 Connect Google Sheets</span>
            {!isGoogleSheetsConnected && (
              <span className="w-2 h-2 rounded-full bg-amber-500"></span>
            )}
          </button>
        </div>

        <div className="p-6 sm:p-8 space-y-6">
          {activeTab === 'signin' ? (
            <>
              {/* Quick Role Login Buttons */}
              <div>
                <div className="flex items-center justify-between mb-2.5">
                  <span className="text-[11px] font-bold uppercase tracking-wider text-slate-500">
                    1-Click Instant Role Access
                  </span>
                  <span className="text-[10px] text-emerald-800 font-bold bg-emerald-50 px-2 py-0.5 rounded-md border border-emerald-200">
                    Pre-Configured Credentials
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
                  Or enter custom credentials
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
                      onChange={(e) => {
                        setUsername(e.target.value);
                        if (error) setError('');
                      }}
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
                      onChange={(e) => {
                        setPassword(e.target.value);
                        if (error) setError('');
                      }}
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
                    {!isGoogleSheetsConnected && (
                      <div className="pt-1.5">
                        <button
                          type="button"
                          onClick={() => setActiveTab('sheets_guide')}
                          className="text-[11px] font-bold text-emerald-800 underline hover:text-emerald-950 inline-flex items-center gap-1"
                        >
                          View Google Sheets setup guide to link live database &rarr;
                        </button>
                      </div>
                    )}
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

              {/* Server Connection Status and Configuration */}
              <div className="pt-4 border-t border-slate-100 flex items-center justify-between text-xs text-slate-500">
                <div className="flex items-center gap-1.5">
                  <span
                    className={`w-2 h-2 rounded-full ${
                      isBackendConnected ? 'bg-emerald-500' : 'bg-amber-500 animate-pulse'
                    }`}
                  />
                  <span>
                    {isBackendConnected
                      ? isGoogleSheetsConnected
                        ? 'Google Sheets Live'
                        : 'FastAPI Online (Sheets Standby)'
                      : 'Connecting / Standby'}
                  </span>
                </div>

                <div className="flex items-center gap-3">
                  {!isGoogleSheetsConnected && (
                    <button
                      type="button"
                      onClick={() => setActiveTab('sheets_guide')}
                      className="text-emerald-800 font-bold hover:underline"
                    >
                      Connect Sheets ↗
                    </button>
                  )}
                  <button
                    type="button"
                    onClick={() => setShowServerConfig(!showServerConfig)}
                    className="inline-flex items-center gap-1 text-slate-500 hover:text-slate-800 font-medium transition-colors cursor-pointer"
                  >
                    <Settings size={13} />
                    <span>{showServerConfig ? 'Close' : 'Server URL'}</span>
                  </button>
                </div>
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
                    <button
                      type="button"
                      onClick={() => setDebugLogs(getApiDebugLogs())}
                      className="px-2.5 py-1 text-slate-500 hover:text-slate-700 text-xs font-semibold rounded-md transition-colors ml-auto flex items-center gap-1 cursor-pointer"
                    >
                      <RefreshCw size={12} />
                      <span>Refresh Logs</span>
                    </button>
                  </div>

                  {/* Real-Time API Diagnostic Logs */}
                  <div className="pt-2 border-t border-slate-200 mt-2 space-y-1.5">
                    <div className="flex items-center justify-between">
                      <span className="font-bold text-[11px] text-slate-700 flex items-center gap-1">
                        <Server size={12} />
                        Recent Connection Attempts ({debugLogs.length})
                      </span>
                      {debugLogs.length > 0 && (
                        <button
                          type="button"
                          onClick={() => {
                            clearApiDebugLogs();
                            setDebugLogs([]);
                          }}
                          className="text-[10px] text-slate-400 hover:text-red-600 cursor-pointer"
                        >
                          Clear
                        </button>
                      )}
                    </div>

                    {debugLogs.length === 0 ? (
                      <div className="text-[11px] text-slate-400 italic py-1">No API calls recorded yet.</div>
                    ) : (
                      <div className="space-y-1.5 max-h-48 overflow-y-auto font-mono text-[10px]">
                        {debugLogs.slice(0, 10).map((log) => (
                          <div
                            key={log.id}
                            className={`p-2 rounded border ${
                              log.ok
                                ? 'bg-emerald-50/70 border-emerald-200 text-emerald-950'
                                : log.failureCategory === 'CORS_RESTRICTION'
                                ? 'bg-red-50 border-red-300 text-red-950'
                                : 'bg-amber-50/80 border-amber-300 text-amber-950'
                            }`}
                          >
                            <div className="flex items-center justify-between font-bold">
                              <span>
                                {log.method} {log.path}
                              </span>
                              <span>
                                {log.ok ? `HTTP ${log.status || 200} ✓` : log.failureCategory || 'FAILED'} ({log.durationMs}ms)
                              </span>
                            </div>
                            <div className="text-[9px] text-slate-500 truncate mt-0.5">
                              Target: {log.targetUrl} {log.isProxied ? '(via Vite Proxy)' : '(Direct)'}
                            </div>
                            {log.diagnostics && (
                              <div className="text-[10px] font-sans font-semibold text-red-800 mt-1 bg-white/70 p-1.5 rounded">
                                {log.diagnostics}
                              </div>
                            )}
                          </div>
                        ))}
                      </div>
                    )}
                  </div>
                </form>
              )}
            </>
          ) : (
            /* Google Sheets Connection Wizard Tab */
            <div className="space-y-5 text-left">
              <div className="bg-emerald-50/70 border border-emerald-200 p-3.5 rounded-xl text-emerald-950 text-xs">
                <div className="font-bold text-emerald-900 flex items-center gap-1.5 text-sm mb-1">
                  <Sparkles size={16} className="text-emerald-700" />
                  <span>Connect Google Sheets & Remove Testing</span>
                </div>
                <p className="m-0 leading-relaxed text-emerald-800">
                  Follow these 3 quick steps using your open browser tabs to transition from Local Standby into Live Production with Google Sheets.
                </p>
              </div>

              {/* Step 1: Spreadsheet ID Extractor */}
              <div className="p-4 bg-white border border-slate-200 rounded-xl space-y-2.5">
                <div className="flex items-center justify-between">
                  <span className="text-xs font-extrabold text-slate-900 flex items-center gap-1.5">
                    <span className="w-5 h-5 rounded-full bg-emerald-100 text-emerald-800 flex items-center justify-center text-[11px] font-black">
                      1
                    </span>
                    Extract Your Spreadsheet ID (Tab 4)
                  </span>
                  <span className="text-[10px] text-slate-500 font-medium">From Google Sheets URL</span>
                </div>

                <p className="text-xs text-slate-600 m-0">
                  Open your <strong>Kawad_Swad_Sales_Management</strong> Google Sheet in browser Tab 4, copy its URL from the address bar, and paste it here:
                </p>

                <div className="flex gap-2">
                  <input
                    type="text"
                    value={sheetUrlInput}
                    onChange={(e) => extractSheetId(e.target.value)}
                    placeholder="https://docs.google.com/spreadsheets/d/1.../edit"
                    className="flex-1 px-3 py-2 text-xs bg-slate-50 border border-slate-300 rounded-lg focus:outline-hidden focus:ring-1 focus:ring-emerald-700 font-mono"
                  />
                  {extractedSheetId && (
                    <button
                      type="button"
                      onClick={() => copyToClipboard(extractedSheetId, 'sheetId')}
                      className="px-3 py-1.5 bg-emerald-800 hover:bg-emerald-900 text-white text-xs font-semibold rounded-lg flex items-center gap-1 shrink-0"
                    >
                      {copiedKey === 'sheetId' ? <Check size={14} /> : <Copy size={14} />}
                      <span>{copiedKey === 'sheetId' ? 'Copied' : 'Copy ID'}</span>
                    </button>
                  )}
                </div>

                {extractedSheetId && (
                  <div className="p-2.5 bg-emerald-50 border border-emerald-200 rounded-lg text-xs font-mono text-emerald-900 break-all flex items-center justify-between">
                    <span>
                      <strong>Extracted ID:</strong> {extractedSheetId}
                    </span>
                  </div>
                )}
              </div>

              {/* Step 2: Share Sheet with Service Account */}
              <div className="p-4 bg-white border border-slate-200 rounded-xl space-y-2">
                <div className="flex items-center justify-between">
                  <span className="text-xs font-extrabold text-slate-900 flex items-center gap-1.5">
                    <span className="w-5 h-5 rounded-full bg-emerald-100 text-emerald-800 flex items-center justify-center text-[11px] font-black">
                      2
                    </span>
                    Share Google Sheet with Service Account
                  </span>
                  <span className="text-[10px] text-slate-500 font-medium">Google Drive Permission</span>
                </div>
                <p className="text-xs text-slate-600 leading-relaxed m-0">
                  In Tab 4 of your Google Sheet, click the top-right green <strong>Share</strong> button. Add your Google Cloud Service Account email (e.g. <code className="bg-slate-100 px-1 py-0.5 rounded text-slate-800">...@...iam.gserviceaccount.com</code>) with <strong>Editor</strong> permission.
                </p>
              </div>

              {/* Step 3: Configure Render Environment */}
              <div className="p-4 bg-white border border-slate-200 rounded-xl space-y-2.5">
                <div className="flex items-center justify-between">
                  <span className="text-xs font-extrabold text-slate-900 flex items-center gap-1.5">
                    <span className="w-5 h-5 rounded-full bg-emerald-100 text-emerald-800 flex items-center justify-center text-[11px] font-black">
                      3
                    </span>
                    Paste in Render Backend (Tab 2)
                  </span>
                  <button
                    type="button"
                    onClick={() => {
                      const snippet = `SALES_GOOGLE_SPREADSHEET_ID=${extractedSheetId || 'YOUR_SPREADSHEET_ID'}\nSALES_ENV=production\nSALES_TESTING=0\nSALES_JWT_SECRET=kawad-swad-production-jwt-signing-secret-2026-nimar`;
                      copyToClipboard(snippet, 'envSnippet');
                    }}
                    className="text-xs font-bold text-emerald-800 hover:text-emerald-950 flex items-center gap-1 cursor-pointer"
                  >
                    {copiedKey === 'envSnippet' ? <Check size={13} /> : <Copy size={13} />}
                    <span>{copiedKey === 'envSnippet' ? 'Copied All' : 'Copy Env Vars'}</span>
                  </button>
                </div>

                <p className="text-xs text-slate-600 m-0">
                  Go to Tab 2 on Render &rarr; <code className="bg-slate-100 px-1 py-0.5 rounded text-slate-800">kawad-swad-sales-backend</code> &rarr; <strong>Environment</strong>, and add:
                </p>

                <div className="bg-slate-900 text-slate-100 p-3 rounded-lg text-xs font-mono space-y-1 overflow-x-auto">
                  <div className="text-emerald-400">SALES_GOOGLE_SPREADSHEET_ID = {extractedSheetId || '(Paste your Sheet ID)'}</div>
                  <div className="text-amber-300">SALES_GOOGLE_SERVICE_ACCOUNT_JSON = (Paste full JSON key)</div>
                  <div>SALES_ENV = production</div>
                  <div>SALES_TESTING = 0</div>
                  <div>SALES_JWT_SECRET = (32+ character random string)</div>
                </div>
              </div>

              {/* Step 4: Reconnect & Verify Buttons */}
              <div className="p-4 bg-slate-50 border border-slate-200 rounded-xl space-y-3">
                <span className="text-xs font-extrabold text-slate-900 block">
                  Step 4: Test Connection & Verify All 28 Sheets
                </span>

                <div className="flex flex-wrap gap-2.5">
                  <button
                    type="button"
                    disabled={isReconnecting}
                    onClick={handleTestReconnect}
                    className="flex-1 min-w-[150px] py-2 px-3 rounded-lg bg-emerald-800 hover:bg-emerald-900 text-white font-semibold text-xs flex items-center justify-center gap-1.5 transition-colors disabled:opacity-50 cursor-pointer"
                  >
                    <RefreshCw size={14} className={isReconnecting ? 'animate-spin' : ''} />
                    <span>{isReconnecting ? 'Testing…' : 'Reconnect Google Sheets'}</span>
                  </button>

                  <button
                    type="button"
                    disabled={isVerifyingTabs}
                    onClick={handleVerifyTabs}
                    className="flex-1 min-w-[150px] py-2 px-3 rounded-lg bg-white border border-slate-300 hover:bg-slate-100 text-slate-800 font-semibold text-xs flex items-center justify-center gap-1.5 transition-colors disabled:opacity-50 cursor-pointer"
                  >
                    <FileSpreadsheet size={14} className={isVerifyingTabs ? 'animate-spin text-emerald-700' : 'text-slate-600'} />
                    <span>{isVerifyingTabs ? 'Checking…' : 'Verify All 28 Tabs'}</span>
                  </button>
                </div>

                {/* Reconnect result feedback */}
                {reconnectResult && (
                  <div
                    className={`p-3 rounded-lg text-xs border ${
                      reconnectResult.success
                        ? 'bg-emerald-50 border-emerald-200 text-emerald-900'
                        : 'bg-red-50 border-red-200 text-red-900'
                    }`}
                  >
                    <div className="font-bold flex items-center gap-1.5">
                      {reconnectResult.success ? <CheckCircle2 size={14} className="text-emerald-700" /> : <AlertCircle size={14} className="text-red-700" />}
                      <span>{reconnectResult.success ? 'Connected to Google Sheets!' : 'Connection Not Established'}</span>
                    </div>
                    <p className="mt-1 m-0">{reconnectResult.message}</p>
                  </div>
                )}

                {/* Verify tabs result feedback */}
                {verifyResult && (
                  <div className="p-3 bg-white border border-slate-200 rounded-lg text-xs space-y-1.5 max-h-48 overflow-y-auto">
                    <div className="font-bold text-slate-800 flex items-center justify-between">
                      <span>Verification Result:</span>
                      <span className={verifyResult.all_tabs_accessible ? 'text-emerald-700 font-bold' : 'text-red-700 font-bold'}>
                        {verifyResult.all_tabs_accessible ? 'All 28 Tabs Verified ✓' : 'Notice / Missing Tabs'}
                      </span>
                    </div>
                    {verifyResult.error && <p className="text-red-600 m-0">{verifyResult.error}</p>}
                    {verifyResult.tabs && (
                      <div className="grid grid-cols-2 gap-1 text-[11px] pt-1 font-mono">
                        {Object.entries(verifyResult.tabs).map(([tName, tInfo]: [string, any]) => (
                          <div key={tName} className="flex items-center justify-between bg-slate-50 px-2 py-1 rounded">
                            <span className="truncate max-w-[120px]">{tName}</span>
                            <span className={tInfo.status === 'ok' ? 'text-emerald-700 font-bold' : 'text-red-600'}>
                              {tInfo.status === 'ok' ? `✓ (${tInfo.columns || 0} cols)` : '✗'}
                            </span>
                          </div>
                        ))}
                      </div>
                    )}
                  </div>
                )}
              </div>

              {/* Bootstrap Owner Account Button & Drawer */}
              <div className="p-4 bg-amber-50/70 border border-amber-200 rounded-xl space-y-3">
                <div className="flex items-center justify-between">
                  <div>
                    <strong className="text-xs font-bold text-amber-950 block">Initialize Owner Account in Sheets</strong>
                    <small className="text-[11px] text-amber-800">
                      If your Google Sheet AuthUsers tab is new and empty, set your owner login:
                    </small>
                  </div>
                  <button
                    type="button"
                    onClick={() => setShowBootstrapForm(!showBootstrapForm)}
                    className="px-2.5 py-1 text-xs font-bold bg-amber-200 hover:bg-amber-300 text-amber-900 rounded-md transition-colors"
                  >
                    {showBootstrapForm ? 'Hide Form' : 'Setup Owner'}
                  </button>
                </div>

                {showBootstrapForm && (
                  <form onSubmit={handleBootstrapOwner} className="space-y-3 pt-2 border-t border-amber-200/80">
                    <div className="grid grid-cols-1 sm:grid-cols-3 gap-2">
                      <div>
                        <label className="block text-[11px] font-semibold text-amber-900 mb-1">Username</label>
                        <input
                          type="text"
                          value={bootstrapUsername}
                          onChange={(e) => setBootstrapUsername(e.target.value)}
                          placeholder="e.g. ankit"
                          required
                          className="w-full px-2.5 py-1.5 text-xs bg-white border border-amber-300 rounded-md"
                        />
                      </div>
                      <div>
                        <label className="block text-[11px] font-semibold text-amber-900 mb-1">Full Name</label>
                        <input
                          type="text"
                          value={bootstrapFullName}
                          onChange={(e) => setBootstrapFullName(e.target.value)}
                          placeholder="Ankit Mandloi"
                          required
                          className="w-full px-2.5 py-1.5 text-xs bg-white border border-amber-300 rounded-md"
                        />
                      </div>
                      <div>
                        <label className="block text-[11px] font-semibold text-amber-900 mb-1">Password</label>
                        <input
                          type="password"
                          value={bootstrapPassword}
                          onChange={(e) => setBootstrapPassword(e.target.value)}
                          placeholder="Min 6 characters"
                          required
                          className="w-full px-2.5 py-1.5 text-xs bg-white border border-amber-300 rounded-md"
                        />
                      </div>
                    </div>

                    {bootstrapStatus && (
                      <div
                        className={`p-2 rounded text-xs ${
                          bootstrapStatus.success ? 'bg-emerald-100 text-emerald-900 font-semibold' : 'bg-red-100 text-red-900'
                        }`}
                      >
                        {bootstrapStatus.message}
                      </div>
                    )}

                    <button
                      type="submit"
                      disabled={isBootstrapping}
                      className="w-full py-2 bg-amber-800 hover:bg-amber-900 text-white text-xs font-bold rounded-lg transition-colors flex items-center justify-center gap-1.5"
                    >
                      {isBootstrapping ? <RefreshCw size={13} className="animate-spin" /> : <Shield size={13} />}
                      <span>Save Owner Login to Google Sheets</span>
                    </button>
                  </form>
                )}
              </div>

              {/* Back to Sign In button */}
              <button
                type="button"
                onClick={() => setActiveTab('signin')}
                className="w-full py-2.5 bg-slate-100 hover:bg-slate-200 text-slate-800 font-bold text-xs rounded-xl transition-colors flex items-center justify-center gap-1.5"
              >
                <span>← Back to Sign In Form</span>
              </button>
            </div>
          )}
        </div>
      </div>
    </div>
  );
};
