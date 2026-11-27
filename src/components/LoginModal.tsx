import React, { useState, useEffect } from 'react';
import { useStore } from '../context/StoreContext';
import { ApiHttpError } from '../services/api';
import {
  Lock,
  User,
  AlertCircle,
  RefreshCw,
  Eye,
  EyeOff,
  Settings,
  Factory,
  Truck,
  Scale,
  ShieldCheck,
  ArrowRight,
  HelpCircle,
  KeyRound,
  CheckCircle2,
  UserCheck,
  Mail,
  Phone,
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
    bootstrapStatus,
    refreshBootstrapStatus,
    bootstrapOwnerAccount,
  } = useStore();

  const [mode, setMode] = useState<'login' | 'bootstrap'>('login');

  // Sign In state
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [rememberUser, setRememberUser] = useState(false);
  const [showPassword, setShowPassword] = useState(false);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<{
    message: string;
    type: 'auth' | 'network' | 'forbidden' | 'setup';
  } | null>(null);
  const [successNotice, setSuccessNotice] = useState<string | null>(null);

  // Gated First Owner Setup state (only usable when server reports !initialized && bootstrap_enabled)
  const [ownerFullName, setOwnerFullName] = useState('');
  const [ownerUsername, setOwnerUsername] = useState('');
  const [ownerPassword, setOwnerPassword] = useState('');
  const [ownerConfirmPassword, setOwnerConfirmPassword] = useState('');
  const [ownerEmail, setOwnerEmail] = useState('');
  const [ownerMobile, setOwnerMobile] = useState('');
  const [bootstrapToken, setBootstrapToken] = useState('');
  const [showOwnerPassword, setShowOwnerPassword] = useState(false);
  const [showBootstrapToken, setShowBootstrapToken] = useState(false);
  const [isBootstrapping, setIsBootstrapping] = useState(false);

  const [showServerConfig, setShowServerConfig] = useState(false);
  const [showHelpNote, setShowHelpNote] = useState(false);
  const [customUrl, setCustomUrl] = useState(backendUrl);

  const canShowOwnerBootstrap = Boolean(
    bootstrapStatus &&
      bootstrapStatus.storage_ready &&
      !bootstrapStatus.initialized &&
      bootstrapStatus.bootstrap_enabled
  );

  const isUninitializedAndLocked = Boolean(
    bootstrapStatus &&
      bootstrapStatus.storage_ready &&
      !bootstrapStatus.initialized &&
      !bootstrapStatus.bootstrap_enabled
  );

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
        // Safe fallback if storage is restricted
      }
    }
  }, []);

  // Probe safe read-only bootstrap status on mount and when backend connectivity changes
  useEffect(() => {
    void refreshBootstrapStatus();
  }, [refreshBootstrapStatus, isBackendConnected]);

  // If system becomes initialized, always return to Sign In mode and wipe bootstrap inputs
  useEffect(() => {
    if (bootstrapStatus?.initialized && mode === 'bootstrap') {
      setMode('login');
      setBootstrapToken('');
      setOwnerPassword('');
      setOwnerConfirmPassword('');
    }
  }, [bootstrapStatus?.initialized, mode]);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (isLoading) return; // Prevent duplicate concurrent submissions
    setError(null);
    setSuccessNotice(null);

    const cleanUser = username.trim();
    if (!cleanUser || !password) {
      setError({
        message: 'Please enter both your User ID / Username and Password to proceed.',
        type: 'auth',
      });
      return;
    }

    // Persist remembered username (strictly username only, never password)
    if (typeof window !== 'undefined') {
      try {
        if (rememberUser) {
          localStorage.setItem(REMEMBERED_USER_KEY, cleanUser);
        } else {
          localStorage.removeItem(REMEMBERED_USER_KEY);
        }
      } catch {
        // Safe fallback
      }
    }

    setIsLoading(true);
    try {
      await login(cleanUser, password);
    } catch (err: unknown) {
      const httpStatus = err instanceof ApiHttpError ? err.status : undefined;
      const rawMsg = err instanceof Error ? err.message : String(err);
      const lower = rawMsg.toLowerCase();

      if (lower.includes('no login accounts exist') || lower.includes('bootstrap')) {
        void refreshBootstrapStatus();
        setError({
          message:
            'No ERP accounts exist yet. Initialize the First Owner account using the one-time server bootstrap token before signing in.',
          type: 'setup',
        });
      } else if (
        httpStatus === 403 ||
        lower.includes('403') ||
        lower.includes('deactivated') ||
        lower.includes('inactive') ||
        lower.includes('legacy') ||
        lower.includes('ambiguous')
      ) {
        setError({
          message: rawMsg.replace(/HTTP \d+:\s*/i, '') || 'Account is deactivated or inactive. Contact the Owner or administrator.',
          type: 'forbidden',
        });
      } else if (
        httpStatus === 429 ||
        lower.includes('429') ||
        lower.includes('quota') ||
        lower.includes('too many') ||
        lower.includes('temporarily locked')
      ) {
        setError({
          message:
            rawMsg.replace(/HTTP \d+:\s*/i, '') ||
            'Too many sign-in attempts detected. Please wait a few minutes before trying again.',
          type: 'network',
        });
      } else if (
        httpStatus === 503 ||
        (httpStatus !== undefined && httpStatus >= 500) ||
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
      } else if (
        httpStatus === 401 ||
        lower.includes('401') ||
        lower.includes('invalid') ||
        lower.includes('unauthorized') ||
        lower.includes('credentials')
      ) {
        setError({
          message: 'The username or password you entered is incorrect. Please check your credentials and try again.',
          type: 'auth',
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

  const handleBootstrapSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (isBootstrapping) return;
    setError(null);
    setSuccessNotice(null);

    const cleanFullName = ownerFullName.trim();
    const cleanUsername = ownerUsername.trim().toLowerCase();
    const cleanToken = bootstrapToken.trim();

    if (!cleanToken) {
      setError({
        message: 'Enter the one-time server bootstrap token from your development environment configuration.',
        type: 'setup',
      });
      return;
    }
    if (cleanFullName.length < 2) {
      setError({
        message: 'Owner full name must be at least 2 characters.',
        type: 'auth',
      });
      return;
    }
    if (!/^[a-z0-9._-]{3,50}$/.test(cleanUsername)) {
      setError({
        message: 'Owner username must be 3–50 characters using letters, numbers, dots, underscores, or hyphens.',
        type: 'auth',
      });
      return;
    }
    if (ownerPassword.length < 12) {
      setError({
        message: 'Owner password must be at least 12 characters long for executive security.',
        type: 'auth',
      });
      return;
    }
    if (ownerPassword !== ownerConfirmPassword) {
      setError({
        message: 'Password and Confirm Password do not match.',
        type: 'auth',
      });
      return;
    }

    setIsBootstrapping(true);
    try {
      const result = await bootstrapOwnerAccount({
        username: cleanUsername,
        fullName: cleanFullName,
        password: ownerPassword,
        bootstrapToken: cleanToken,
        email: ownerEmail.trim(),
        mobile: ownerMobile.trim(),
      });

      if (result.success) {
        // Clear all sensitive fields immediately
        setBootstrapToken('');
        setOwnerPassword('');
        setOwnerConfirmPassword('');
        setUsername(result.data?.username || cleanUsername);
        setPassword('');
        setMode('login');
        setSuccessNotice(
          `First Owner account "${result.data?.username || cleanUsername}" initialized as OWNER_ADMIN. Sign in below with your new credentials.`
        );
      } else {
        setError({
          message: result.message || 'First Owner initialization was rejected by the server.',
          type: result.errorCode === 'OWNER_ALREADY_INITIALIZED' ? 'forbidden' : 'auth',
        });
      }
    } finally {
      setIsBootstrapping(false);
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
        label: 'API Standby',
        dot: 'bg-amber-400',
        text: 'text-amber-800',
      };
    }
    if (!isGoogleSheetsConnected) {
      return {
        label: 'API Connected · Sheets Offline',
        dot: 'bg-amber-400',
        text: 'text-amber-800',
      };
    }
    if (!persistentWritesEnabled) {
      return {
        label: 'API Connected · Storage Standby',
        dot: 'bg-amber-400 animate-pulse',
        text: 'text-amber-800',
      };
    }
    return {
      label: 'System Online · Storage Verified',
      dot: 'bg-emerald-400',
      text: 'text-emerald-300',
    };
  };

  const connState = getConnectionState();

  return (
    <div className="min-h-screen w-full bg-[#F8F6F0] flex flex-col lg:flex-row items-stretch select-none font-sans text-slate-800">
      {/* ------------------------------------------------------------------ */}
      {/* LEFT SECTION: BRAND IDENTITY & OPERATIONAL PILLARS (Desktop)       */}
      {/* ------------------------------------------------------------------ */}
      <div className="hidden lg:flex lg:w-[48%] xl:w-[44%] bg-[#0F2C23] text-white flex-col justify-between p-12 xl:p-16 relative overflow-hidden shrink-0 shadow-2xl">
        {/* Subtle, refined atmospheric lighting */}
        <div className="absolute -right-24 -bottom-24 w-96 h-96 rounded-full bg-emerald-600/10 blur-3xl pointer-events-none" />
        <div className="absolute -left-20 -top-20 w-80 h-80 rounded-full bg-[#184638]/40 blur-3xl pointer-events-none" />

        {/* Top Header: Brand Emblem & ERP Identity */}
        <div className="relative z-10">
          <div className="flex items-center gap-3.5 mb-10">
            {/* Elegant Monogram Badge */}
            <div className="w-12 h-12 rounded-xl bg-white text-[#0F2C23] flex items-center justify-center font-black text-xl shadow-lg border border-amber-100/50 tracking-tighter shrink-0">
              KS
            </div>
            <div>
              <span className="text-[11px] font-bold tracking-[0.2em] text-[#D8B468] uppercase block leading-none mb-1.5">
                Kawad Swad Udhyog
              </span>
              <span className="text-xl font-bold tracking-tight text-white block leading-tight" style={{ color: '#ffffff' }}>
                Enterprise Resource Planning
              </span>
            </div>
          </div>

          <div className="inline-flex items-center gap-2 px-3 py-1 rounded-md text-[11px] font-semibold bg-white/10 border border-white/15 text-emerald-200 backdrop-blur-xs mb-8">
            <span className="w-1.5 h-1.5 rounded-full bg-[#D8B468]" />
            <span style={{ color: '#A7F3D0' }}>Nimar Agro-Industrial Operations</span>
          </div>

          <h1 className="text-3xl xl:text-4xl font-extrabold tracking-tight leading-snug !text-white" style={{ color: '#ffffff' }}>
            Business Management System
          </h1>
          <p className="mt-3 text-base font-medium tracking-wide !text-emerald-100" style={{ color: '#D1FAE5' }}>
            One System. Every Operation.
          </p>
        </div>

        {/* Middle: Authentic Operational Pillars */}
        <div className="my-8 space-y-3.5 relative z-10">
          <div className="flex items-start gap-3.5 p-3.5 rounded-xl bg-white/5 border border-white/10 backdrop-blur-xs transition-colors hover:bg-white/8">
            <div className="w-9 h-9 rounded-lg bg-emerald-950/90 border border-emerald-700/50 flex items-center justify-center text-emerald-300 shrink-0 mt-0.5 shadow-xs">
              <Factory size={18} />
            </div>
            <div>
              <h2 className="text-sm font-bold !text-white m-0" style={{ color: '#ffffff' }}>Factory &amp; Milling Operations</h2>
              <p className="text-xs !text-emerald-100/80 mt-1 leading-relaxed m-0" style={{ color: '#D1FAE5' }}>
                Moong &amp; chana pulse milling, dynamic recipe bill of materials, packaging batches, and floor muster rolls.
              </p>
            </div>
          </div>

          <div className="flex items-start gap-3.5 p-3.5 rounded-xl bg-white/5 border border-white/10 backdrop-blur-xs transition-colors hover:bg-white/8">
            <div className="w-9 h-9 rounded-lg bg-emerald-950/90 border border-emerald-700/50 flex items-center justify-center text-emerald-300 shrink-0 mt-0.5 shadow-xs">
              <Truck size={18} />
            </div>
            <div>
              <h2 className="text-sm font-bold !text-white m-0" style={{ color: '#ffffff' }}>Field Sales &amp; Van Inventory</h2>
              <p className="text-xs !text-emerald-100/80 mt-1 leading-relaxed m-0" style={{ color: '#D1FAE5' }}>
                Live shopkeeper route billing, van vehicle stock balances, instant receipts, and cash closing.
              </p>
            </div>
          </div>

          <div className="flex items-start gap-3.5 p-3.5 rounded-xl bg-white/5 border border-white/10 backdrop-blur-xs transition-colors hover:bg-white/8">
            <div className="w-9 h-9 rounded-lg bg-emerald-950/90 border border-emerald-700/50 flex items-center justify-center text-emerald-300 shrink-0 mt-0.5 shadow-xs">
              <Scale size={18} />
            </div>
            <div>
              <h2 className="text-sm font-bold !text-white m-0" style={{ color: '#ffffff' }}>Double-Entry Financial Ledgers</h2>
              <p className="text-xs !text-emerald-100/80 mt-1 leading-relaxed m-0" style={{ color: '#D1FAE5' }}>
                Trial balances, customer receivables, supplier payables, workforce payroll, and bank disbursements.
              </p>
            </div>
          </div>
        </div>

        {/* Bottom: Heritage & System Health */}
        <div className="pt-6 border-t border-emerald-800/40 flex items-center justify-between text-xs text-emerald-200/80 relative z-10">
          <div>
            <span className="font-semibold text-white block" style={{ color: '#ffffff' }}>Kawad Swad Udhyog</span>
            <span className="text-[11px] text-[#D8B468]">Nimar Region, Madhya Pradesh · Est. 1998</span>
          </div>

          <div className="inline-flex items-center gap-2 px-3 py-1.5 rounded-lg bg-black/25 border border-white/10 text-[11px] font-medium text-emerald-200">
            <span className={`w-2 h-2 rounded-full ${connState.dot}`} />
            <span style={{ color: '#E2E8F0' }}>{connState.label}</span>
          </div>
        </div>
      </div>

      {/* ------------------------------------------------------------------ */}
      {/* RIGHT SECTION: CLEAN, FOCUSED & ACCESSIBLE LOGIN / SETUP CARD      */}
      {/* ------------------------------------------------------------------ */}
      <div className="flex-1 flex flex-col justify-center items-center p-6 sm:p-10 lg:p-16">
        {/* Mobile Header Branding (Visible on mobile/tablet viewports) */}
        <div className="lg:hidden w-full max-w-md text-center mb-6">
          <div className="inline-flex items-center justify-center w-12 h-12 rounded-xl bg-[#0F2C23] text-white font-black text-xl mb-3 shadow-md border border-amber-200/20">
            KS
          </div>
          <span className="text-[11px] font-bold tracking-[0.18em] text-[#A67C38] uppercase block leading-none mb-1">
            Kawad Swad Udhyog
          </span>
          <h2 className="text-xl font-bold text-slate-900 tracking-tight m-0">
            Business Management System
          </h2>
          <p className="text-xs text-slate-500 mt-1 m-0">
            One System. Every Operation.
          </p>
        </div>

        {/* Main Card */}
        <div className="w-full max-w-md bg-white border border-[#E7E2D6] rounded-2xl shadow-[0_10px_35px_-10px_rgba(15,44,35,0.07)] p-8 sm:p-10 relative">
          {/* Card Title & Instructions */}
          <div className="mb-6">
            <div className="flex items-center justify-between gap-2">
              <h2 className="text-2xl font-bold text-slate-900 tracking-tight m-0">
                {mode === 'bootstrap' ? 'First Owner Setup' : 'Staff Sign In'}
              </h2>
              <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-md text-[11px] font-bold bg-[#F4F1EA] text-[#0F2C23] border border-[#DDD7C9] shrink-0">
                <ShieldCheck size={13} className="text-[#0F2C23]" />
                {mode === 'bootstrap' ? 'One-Time Setup' : 'Secure Portal'}
              </span>
            </div>
            <p className="text-xs text-slate-500 mt-2 leading-relaxed m-0">
              {mode === 'bootstrap'
                ? 'Initialize the sole First Owner (OWNER_ADMIN) account using your one-time server bootstrap token.'
                : 'Enter your assigned staff credentials to access your daily operational workspace.'}
            </p>
          </div>

          {/* Gated First Owner Setup Mode Switcher (Visible ONLY when uninitialized & enabled) */}
          {canShowOwnerBootstrap && (
            <div className="mb-5 p-1 bg-[#F4F1EA] border border-[#DDD7C9] rounded-xl grid grid-cols-2 gap-1">
              <button
                type="button"
                data-testid="mode-tab-login"
                onClick={() => {
                  setMode('login');
                  setError(null);
                }}
                className={`py-2 px-3 rounded-lg text-xs font-bold transition-colors cursor-pointer ${
                  mode === 'login'
                    ? 'bg-white text-[#0F2C23] shadow-xs border border-[#E7E2D6]'
                    : 'text-slate-600 hover:text-slate-900'
                }`}
              >
                Staff Sign In
              </button>
              <button
                type="button"
                data-testid="mode-tab-bootstrap"
                onClick={() => {
                  setMode('bootstrap');
                  setError(null);
                  setSuccessNotice(null);
                }}
                className={`py-2 px-3 rounded-lg text-xs font-bold transition-colors cursor-pointer ${
                  mode === 'bootstrap'
                    ? 'bg-[#0F2C23] text-white shadow-xs'
                    : 'text-[#0F2C23] hover:bg-white/60'
                }`}
              >
                First Owner Setup
              </button>
            </div>
          )}

          {/* Uninitialized but server bootstrap disabled notice */}
          {isUninitializedAndLocked && mode === 'login' && (
            <div
              data-testid="bootstrap-disabled-notice"
              className="mb-5 p-3.5 rounded-xl bg-amber-50 border border-amber-200 text-amber-900 text-xs space-y-1"
            >
              <div className="flex items-center gap-1.5 font-bold">
                <KeyRound size={14} className="text-amber-700 shrink-0" />
                <span>Initial Owner Setup Required</span>
              </div>
              <p className="m-0 leading-relaxed text-[11px] text-amber-900/90">
                No accounts exist yet and one-time bootstrap is currently disabled. Configure{' '}
                <code className="font-mono font-semibold">SALES_OWNER_BOOTSTRAP_ENABLED=true</code>,{' '}
                <code className="font-mono font-semibold">SALES_OWNER_BOOTSTRAP_SECRET</code>, and{' '}
                <code className="font-mono font-semibold">SALES_OWNER_BOOTSTRAP_EXPIRES_AT</code> on the development server, or run{' '}
                <code className="font-mono font-semibold">backend/scripts/initialize_first_owner.py</code>.
              </p>
            </div>
          )}

          {/* Success Notice (after First Owner Setup) */}
          {successNotice && (
            <div
              data-testid="auth-success-notice"
              className="mb-5 p-3.5 rounded-xl bg-emerald-50 border border-emerald-200 text-emerald-900 text-xs space-y-1"
            >
              <div className="flex items-center gap-1.5 font-bold">
                <CheckCircle2 size={15} className="text-emerald-700 shrink-0" />
                <span>Owner Account Initialized</span>
              </div>
              <p className="m-0 leading-relaxed font-medium">{successNotice}</p>
            </div>
          )}

          {mode === 'bootstrap' && canShowOwnerBootstrap ? (
            /* ---------------------------------------------------------------- */
            /* GATED ONE-TIME FIRST OWNER INITIALIZATION FORM                   */
            /* ---------------------------------------------------------------- */
            <form onSubmit={handleBootstrapSubmit} className="space-y-3.5" data-testid="owner-bootstrap-form">
              <div>
                <label
                  className="block text-xs font-bold uppercase tracking-wider text-slate-700 mb-1"
                  htmlFor="bootstrap-token"
                >
                  One-Time Server Bootstrap Token
                </label>
                <div className="relative flex items-center">
                  <span className="absolute left-3.5 text-slate-400 pointer-events-none flex items-center">
                    <KeyRound size={16} />
                  </span>
                  <input
                    id="bootstrap-token"
                    type={showBootstrapToken ? 'text' : 'password'}
                    value={bootstrapToken}
                    onChange={(e) => {
                      setBootstrapToken(e.target.value);
                      if (error) setError(null);
                    }}
                    autoComplete="off"
                    required
                    placeholder="Enter server bootstrap secret"
                    disabled={isBootstrapping}
                    style={{ paddingLeft: '42px', paddingRight: '42px' }}
                    className="w-full py-2.5 text-sm bg-white border border-slate-300 rounded-xl focus:outline-hidden focus:ring-2 focus:ring-[#0F2C23] focus:border-[#0F2C23] transition-colors disabled:bg-slate-50 font-mono placeholder:font-sans placeholder:text-slate-400"
                  />
                  <button
                    type="button"
                    onClick={() => setShowBootstrapToken(!showBootstrapToken)}
                    className="absolute right-3 text-slate-400 hover:text-slate-700 transition-colors cursor-pointer p-1"
                    tabIndex={-1}
                    aria-label={showBootstrapToken ? 'Hide bootstrap token' : 'Show bootstrap token'}
                  >
                    {showBootstrapToken ? <EyeOff size={16} /> : <Eye size={16} />}
                  </button>
                </div>
              </div>

              <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                <div>
                  <label
                    className="block text-xs font-bold uppercase tracking-wider text-slate-700 mb-1"
                    htmlFor="bootstrap-fullname"
                  >
                    Owner Full Name
                  </label>
                  <div className="relative flex items-center">
                    <span className="absolute left-3 text-slate-400 pointer-events-none flex items-center">
                      <UserCheck size={15} />
                    </span>
                    <input
                      id="bootstrap-fullname"
                      type="text"
                      value={ownerFullName}
                      onChange={(e) => {
                        setOwnerFullName(e.target.value);
                        if (error) setError(null);
                      }}
                      required
                      minLength={2}
                      placeholder="e.g. Rajesh Kawad"
                      disabled={isBootstrapping}
                      style={{ paddingLeft: '36px', paddingRight: '12px' }}
                      className="w-full py-2.5 text-sm bg-white border border-slate-300 rounded-xl focus:outline-hidden focus:ring-2 focus:ring-[#0F2C23] focus:border-[#0F2C23] disabled:bg-slate-50"
                    />
                  </div>
                </div>

                <div>
                  <label
                    className="block text-xs font-bold uppercase tracking-wider text-slate-700 mb-1"
                    htmlFor="bootstrap-username"
                  >
                    Owner Username
                  </label>
                  <div className="relative flex items-center">
                    <span className="absolute left-3 text-slate-400 pointer-events-none flex items-center">
                      <User size={15} />
                    </span>
                    <input
                      id="bootstrap-username"
                      type="text"
                      value={ownerUsername}
                      onChange={(e) => {
                        setOwnerUsername(e.target.value);
                        if (error) setError(null);
                      }}
                      required
                      minLength={3}
                      autoComplete="username"
                      placeholder="e.g. owner"
                      disabled={isBootstrapping}
                      style={{ paddingLeft: '36px', paddingRight: '12px' }}
                      className="w-full py-2.5 text-sm bg-white border border-slate-300 rounded-xl focus:outline-hidden focus:ring-2 focus:ring-[#0F2C23] focus:border-[#0F2C23] disabled:bg-slate-50"
                    />
                  </div>
                </div>
              </div>

              <div>
                <label
                  className="block text-xs font-bold uppercase tracking-wider text-slate-700 mb-1"
                  htmlFor="bootstrap-password"
                >
                  Owner Password (min 12 chars)
                </label>
                <div className="relative flex items-center">
                  <span className="absolute left-3.5 text-slate-400 pointer-events-none flex items-center">
                    <Lock size={16} />
                  </span>
                  <input
                    id="bootstrap-password"
                    type={showOwnerPassword ? 'text' : 'password'}
                    value={ownerPassword}
                    onChange={(e) => {
                      setOwnerPassword(e.target.value);
                      if (error) setError(null);
                    }}
                    required
                    minLength={12}
                    autoComplete="new-password"
                    placeholder="Choose a strong 12+ character password"
                    disabled={isBootstrapping}
                    style={{ paddingLeft: '42px', paddingRight: '42px' }}
                    className="w-full py-2.5 text-sm bg-white border border-slate-300 rounded-xl focus:outline-hidden focus:ring-2 focus:ring-[#0F2C23] focus:border-[#0F2C23] disabled:bg-slate-50"
                  />
                  <button
                    type="button"
                    onClick={() => setShowOwnerPassword(!showOwnerPassword)}
                    className="absolute right-3 text-slate-400 hover:text-slate-700 transition-colors cursor-pointer p-1"
                    tabIndex={-1}
                    aria-label={showOwnerPassword ? 'Hide password' : 'Show password'}
                  >
                    {showOwnerPassword ? <EyeOff size={16} /> : <Eye size={16} />}
                  </button>
                </div>
              </div>

              <div>
                <label
                  className="block text-xs font-bold uppercase tracking-wider text-slate-700 mb-1"
                  htmlFor="bootstrap-confirm-password"
                >
                  Confirm Password
                </label>
                <div className="relative flex items-center">
                  <span className="absolute left-3.5 text-slate-400 pointer-events-none flex items-center">
                    <Lock size={16} />
                  </span>
                  <input
                    id="bootstrap-confirm-password"
                    type={showOwnerPassword ? 'text' : 'password'}
                    value={ownerConfirmPassword}
                    onChange={(e) => {
                      setOwnerConfirmPassword(e.target.value);
                      if (error) setError(null);
                    }}
                    required
                    minLength={12}
                    autoComplete="new-password"
                    placeholder="Re-enter password"
                    disabled={isBootstrapping}
                    style={{ paddingLeft: '42px', paddingRight: '14px' }}
                    className="w-full py-2.5 text-sm bg-white border border-slate-300 rounded-xl focus:outline-hidden focus:ring-2 focus:ring-[#0F2C23] focus:border-[#0F2C23] disabled:bg-slate-50"
                  />
                </div>
              </div>

              <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                <div>
                  <label
                    className="block text-[11px] font-bold uppercase tracking-wider text-slate-600 mb-1"
                    htmlFor="bootstrap-email"
                  >
                    Email (Optional)
                  </label>
                  <div className="relative flex items-center">
                    <span className="absolute left-3 text-slate-400 pointer-events-none flex items-center">
                      <Mail size={14} />
                    </span>
                    <input
                      id="bootstrap-email"
                      type="email"
                      value={ownerEmail}
                      onChange={(e) => setOwnerEmail(e.target.value)}
                      placeholder="owner@company.com"
                      disabled={isBootstrapping}
                      style={{ paddingLeft: '34px', paddingRight: '10px' }}
                      className="w-full py-2 text-xs bg-white border border-slate-300 rounded-xl focus:outline-hidden focus:ring-2 focus:ring-[#0F2C23] focus:border-[#0F2C23] disabled:bg-slate-50"
                    />
                  </div>
                </div>

                <div>
                  <label
                    className="block text-[11px] font-bold uppercase tracking-wider text-slate-600 mb-1"
                    htmlFor="bootstrap-mobile"
                  >
                    Mobile (Optional)
                  </label>
                  <div className="relative flex items-center">
                    <span className="absolute left-3 text-slate-400 pointer-events-none flex items-center">
                      <Phone size={14} />
                    </span>
                    <input
                      id="bootstrap-mobile"
                      type="tel"
                      value={ownerMobile}
                      onChange={(e) => setOwnerMobile(e.target.value)}
                      placeholder="+91 98XXXXXXXX"
                      disabled={isBootstrapping}
                      style={{ paddingLeft: '34px', paddingRight: '10px' }}
                      className="w-full py-2 text-xs bg-white border border-slate-300 rounded-xl focus:outline-hidden focus:ring-2 focus:ring-[#0F2C23] focus:border-[#0F2C23] disabled:bg-slate-50"
                    />
                  </div>
                </div>
              </div>

              <p className="text-[11px] text-slate-500 m-0 leading-relaxed">
                Role is strictly assigned by the server as <strong className="text-[#0F2C23]">OWNER_ADMIN</strong>. Setup permanently locks after the first Owner is created.
              </p>

              {/* Error Message Alert */}
              {error && (
                <div
                  role="alert"
                  data-testid="auth-error-alert"
                  className={`p-3.5 rounded-xl text-xs space-y-1 border ${
                    error.type === 'auth'
                      ? 'bg-rose-50 border-rose-200 text-rose-900'
                      : error.type === 'network' || error.type === 'setup'
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
                      {error.type === 'forbidden'
                        ? 'Initialization Locked'
                        : error.type === 'setup'
                        ? 'Setup Requirement'
                        : 'Initialization Notice'}
                    </span>
                  </div>
                  <p className="m-0 leading-relaxed font-medium">{error.message}</p>
                </div>
              )}

              <button
                type="submit"
                disabled={isBootstrapping}
                data-testid="bootstrap-submit-btn"
                className="w-full py-3.5 px-4 rounded-xl bg-[#0F2C23] hover:bg-[#153D31] active:bg-[#0A201A] text-white font-bold text-sm shadow-sm transition-all flex items-center justify-center gap-2 cursor-pointer disabled:opacity-60 disabled:cursor-not-allowed mt-2"
              >
                {isBootstrapping ? (
                  <>
                    <RefreshCw size={16} className="animate-spin text-white" />
                    <span>Initializing Owner Account…</span>
                  </>
                ) : (
                  <>
                    <span>Initialize First Owner Account</span>
                    <ArrowRight size={15} className="text-emerald-300" />
                  </>
                )}
              </button>
            </form>
          ) : (
            /* ---------------------------------------------------------------- */
            /* STANDARD STAFF SIGN IN FORM                                      */
            /* ---------------------------------------------------------------- */
            <form onSubmit={handleSubmit} className="space-y-4" data-testid="login-form">
              {/* Username / User ID Field */}
              <div>
                <label
                  className="block text-xs font-bold uppercase tracking-wider text-slate-700 mb-1.5"
                  htmlFor="login-username"
                >
                  User ID / Username
                </label>
                <div className="relative flex items-center">
                  <span className="absolute left-3.5 text-slate-400 pointer-events-none flex items-center">
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
                    placeholder="e.g. owner, ramesh_sales, factory_mgr"
                    disabled={isLoading}
                    style={{ paddingLeft: '44px', paddingRight: '14px' }}
                    className="w-full py-3 text-sm bg-white border border-slate-300 rounded-xl focus:outline-hidden focus:ring-2 focus:ring-[#0F2C23] focus:border-[#0F2C23] transition-colors disabled:bg-slate-50 disabled:text-slate-500 font-medium placeholder:text-slate-400"
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
                <div className="relative flex items-center">
                  <span className="absolute left-3.5 text-slate-400 pointer-events-none flex items-center">
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
                    style={{ paddingLeft: '44px', paddingRight: '44px' }}
                    className="w-full py-3 text-sm bg-white border border-slate-300 rounded-xl focus:outline-hidden focus:ring-2 focus:ring-[#0F2C23] focus:border-[#0F2C23] transition-colors disabled:bg-slate-50 disabled:text-slate-500 font-medium placeholder:text-slate-400"
                  />
                  <button
                    type="button"
                    onClick={() => setShowPassword(!showPassword)}
                    className="absolute right-3 text-slate-400 hover:text-slate-700 transition-colors cursor-pointer p-1"
                    tabIndex={-1}
                    aria-label={showPassword ? 'Hide password' : 'Show password'}
                  >
                    {showPassword ? <EyeOff size={17} /> : <Eye size={17} />}
                  </button>
                </div>
              </div>

              {/* Remember Username Option & Staff Support Note */}
              <div className="flex items-center justify-between pt-1 gap-2">
                <label
                  style={{ display: 'inline-flex', alignItems: 'center', cursor: 'pointer' }}
                  className="text-xs font-medium text-slate-600 select-none cursor-pointer"
                >
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
                    className="w-4 h-4 shrink-0 rounded text-[#0F2C23] focus:ring-[#0F2C23] border-slate-300 cursor-pointer mr-2"
                  />
                  <span className="truncate">Remember User ID on this device</span>
                </label>

                <button
                  type="button"
                  onClick={() => setShowHelpNote(!showHelpNote)}
                  className="text-xs text-slate-500 hover:text-[#0F2C23] transition-colors inline-flex items-center gap-1 cursor-pointer font-medium shrink-0"
                  title="Forgot Password or Account Help"
                >
                  <HelpCircle size={13} />
                  <span>Help</span>
                </button>
              </div>

              {/* Help Callout for Password Reset & Access Support */}
              {showHelpNote && (
                <div className="p-3 bg-[#FAF8F3] border border-[#E7E2D6] rounded-xl text-xs text-slate-600 space-y-1">
                  <p className="font-semibold text-slate-800 m-0">Need account access or password reset?</p>
                  <p className="m-0 leading-relaxed text-slate-600 text-[11px]">
                    Passcode credentials are managed centrally. Please contact your factory supervisor, personal assistant (PA), or the system administrator to reset your credentials.
                  </p>
                </div>
              )}

              {/* Error Message Alert */}
              {error && (
                <div
                  role="alert"
                  data-testid="auth-error-alert"
                  className={`p-3.5 rounded-xl text-xs space-y-1 border ${
                    error.type === 'auth'
                      ? 'bg-rose-50 border-rose-200 text-rose-900'
                      : error.type === 'network' || error.type === 'setup'
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
                        ? 'Authentication Notice'
                        : error.type === 'network'
                        ? 'Connection Notice'
                        : error.type === 'setup'
                        ? 'Initialization Required'
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
                data-testid="login-submit-btn"
                className="w-full py-3.5 px-4 rounded-xl bg-[#0F2C23] hover:bg-[#153D31] active:bg-[#0A201A] text-white font-bold text-sm shadow-sm transition-all flex items-center justify-center gap-2 cursor-pointer disabled:opacity-60 disabled:cursor-not-allowed mt-3"
              >
                {isLoading ? (
                  <>
                    <RefreshCw size={16} className="animate-spin text-white" />
                    <span>Signing In…</span>
                  </>
                ) : (
                  <>
                    <span>Sign In to ERP</span>
                    <ArrowRight size={15} className="text-emerald-300" />
                  </>
                )}
              </button>
            </form>
          )}

          {/* Footer Controls: Live Connection State & Optional Server Config */}
          <div className="mt-7 pt-4 border-t border-slate-100 flex items-center justify-between text-xs">
            <div className="flex items-center gap-1.5">
              <span className={`w-2 h-2 rounded-full ${connState.dot}`} />
              <span className="text-[11px] font-medium text-slate-500">
                {connState.label}
              </span>
            </div>

            {typeof window !== 'undefined' &&
              (['localhost', '127.0.0.1', '::1'].includes(window.location.hostname) ||
                window.location.hostname.endsWith('.local')) && (
                <button
                  type="button"
                  onClick={() => setShowServerConfig(!showServerConfig)}
                  className="inline-flex items-center gap-1 text-slate-400 hover:text-slate-700 text-[11px] font-medium transition-colors cursor-pointer"
                  title="Configure Local Development Backend Endpoint"
                >
                  <Settings size={12} />
                  <span>{showServerConfig ? 'Close' : 'Server Config'}</span>
                </button>
              )}
          </div>

          {/* Collapsible Server Configuration Panel (Local Development Only) */}
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
                placeholder="http://127.0.0.1:8000 (blank = same-origin proxy)"
                className="w-full px-2.5 py-1.5 text-xs bg-white border border-slate-300 rounded-lg focus:outline-hidden focus:ring-1 focus:ring-[#0F2C23] font-mono"
              />
              <div className="flex items-center gap-2 pt-1">
                <button
                  type="submit"
                  className="px-3 py-1 bg-[#0F2C23] hover:bg-[#153D31] text-white text-xs font-semibold rounded-lg transition-colors cursor-pointer"
                >
                  Apply URL
                </button>
                <button
                  type="button"
                  onClick={() => {
                    setCustomUrl('');
                    updateBackendUrl('');
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

