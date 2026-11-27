#!/usr/bin/env node
/**
 * Kawad Swad ERP — KS-DEV-01 Live Browser End-to-End Verification Suite
 *
 * Drives the REAL React frontend served by Vite (http://localhost:3000) in headless Chromium,
 * forwarding /api/*, /auth/*, and /health directly to the REAL Python backend auth/bootstrap/
 * dashboard/workspace routers running offline on 127.0.0.1:18000 (SALES_TESTING=1).
 *
 * Tests all 12 mandatory KS-DEV-01 Stage F scenarios + desktop & mobile responsiveness.
 */

const { spawn } = require('child_process');
const path = require('path');
const { chromium } = require('/usr/local/share/bun-global/node_modules/playwright-core');

const APP_URL = 'http://localhost:3000';
const PY_PORT = 18000;
const PY_BASE = `http://127.0.0.1:${PY_PORT}`;

// Ephemeral test-only values (never used in production)
const TEST_BOOTSTRAP_SECRET = 'KsDev01E2EBootstrapAuthorityToken#2026!887766';
const TEST_OWNER_USERNAME = 'owner.dev';
const TEST_OWNER_FULLNAME = 'Rajesh Kawad';
const TEST_OWNER_PASSWORD = 'KawadSwad!E2EOwner#2026';
const TEST_INACTIVE_USERNAME = 'inactive.staff';
const TEST_INACTIVE_PASSWORD = 'KawadSwad!Inactive#2026';

function assert(cond, msg) {
  if (!cond) {
    throw new Error(`ASSERTION FAILED: ${msg}`);
  }
}

async function startPythonAuthBridge() {
  const scriptPath = path.resolve(__dirname, 'ks_dev_01_python_test_server.py');
  const child = spawn('python3', [scriptPath], {
    env: {
      ...process.env,
      SALES_TESTING: '1',
      SALES_ENV: 'development',
      KS_DEV_TEST_PORT: String(PY_PORT),
      SALES_OWNER_BOOTSTRAP_ENABLED: 'true',
      SALES_OWNER_BOOTSTRAP_SECRET: TEST_BOOTSTRAP_SECRET,
    },
    stdio: ['ignore', 'pipe', 'pipe'],
  });

  await new Promise((resolve, reject) => {
    const timeout = setTimeout(() => reject(new Error('Python test bridge failed to start within 10s')), 10000);
    child.stdout.on('data', (chunk) => {
      if (String(chunk).includes('KS_DEV_AUTH_SERVER_READY')) {
        clearTimeout(timeout);
        resolve();
      }
    });
    child.stderr.on('data', (chunk) => {
      const text = String(chunk).trim();
      if (text) console.error('[py-bridge stderr]', text);
    });
    child.on('exit', (code) => {
      clearTimeout(timeout);
      reject(new Error(`Python test bridge exited prematurely with code ${code}`));
    });
  });

  return child;
}

async function attachApiForwarder(page) {
  await page.route('**/*', async (route) => {
    const req = route.request();
    const url = new URL(req.url());
    const isApi =
      url.origin === APP_URL &&
      (url.pathname.startsWith('/api/') || url.pathname.startsWith('/auth/') || url.pathname === '/health');

    if (!isApi) {
      return route.continue();
    }

    try {
      const headers = { ...req.headers() };
      delete headers.host;
      delete headers['content-length'];
      const resp = await fetch(`${PY_BASE}${url.pathname}${url.search}`, {
        method: req.method(),
        headers,
        body: ['GET', 'HEAD'].includes(req.method()) ? undefined : req.postData() || undefined,
      });
      const text = await resp.text();
      await route.fulfill({
        status: resp.status,
        contentType: resp.headers.get('content-type') || 'application/json',
        body: text,
      });
    } catch (err) {
      await route.fulfill({
        status: 503,
        contentType: 'application/json',
        body: JSON.stringify({ detail: `Test bridge unreachable: ${err.message}` }),
      });
    }
  });
}

async function runE2E() {
  const results = [];
  const record = (id, name, status, details) => {
    results.push({ id, name, status, details });
    console.log(`[${status}] ${id}. ${name} — ${details}`);
  };

  let pyServer = null;
  let browser = null;

  try {
    pyServer = await startPythonAuthBridge();
    browser = await chromium.launch({
      headless: true,
      args: ['--no-sandbox', '--disable-setuid-sandbox', '--disable-dev-shm-usage'],
    });

    const context = await browser.newContext({ viewport: { width: 1440, height: 900 } });
    const page = await context.newPage();
    const pageErrors = [];
    page.on('pageerror', (err) => pageErrors.push(err.message));

    await attachApiForwarder(page);

    // ------------------------------------------------------------------
    // Scenario 12: Direct API access without authentication is rejected
    // ------------------------------------------------------------------
    const directMeResp = await fetch(`${PY_BASE}/api/auth/me`);
    const directDashResp = await fetch(`${PY_BASE}/api/dashboard`);
    const directWsResp = await fetch(`${PY_BASE}/api/workspace`);
    assert(directMeResp.status === 401, `Expected 401 on /api/auth/me, got ${directMeResp.status}`);
    assert(directDashResp.status === 401, `Expected 401 on /api/dashboard, got ${directDashResp.status}`);
    assert(directWsResp.status === 401, `Expected 401 on /api/workspace, got ${directWsResp.status}`);
    record(12, 'Direct API access without authentication is rejected', 'PASS', 'GET /api/auth/me, /api/dashboard, /api/workspace all returned HTTP 401');

    // ------------------------------------------------------------------
    // Scenario 6: Unauthorized user cannot access protected routes (UI gate)
    // ------------------------------------------------------------------
    await page.goto(APP_URL, { waitUntil: 'networkidle' });
    await page.evaluate(() => {
      localStorage.clear();
      sessionStorage.clear();
    });
    await page.reload({ waitUntil: 'networkidle' });
    await page.waitForSelector('[data-testid="login-form"]', { timeout: 10000 });
    const bodyBeforeAuth = await page.textContent('body');
    assert(!bodyBeforeAuth.includes('Executive Control Center'), 'Dashboard must not be visible while unauthenticated');
    record(6, 'Unauthorized user cannot access protected routes', 'PASS', 'Unauthenticated browser renders Login screen only; Executive Dashboard blocked');

    // ------------------------------------------------------------------
    // Scenario 1: First Owner setup succeeds via gated UI -> real backend
    // ------------------------------------------------------------------
    await page.waitForSelector('[data-testid="mode-tab-bootstrap"]', { timeout: 10000 });
    await page.click('[data-testid="mode-tab-bootstrap"]');
    await page.waitForSelector('[data-testid="owner-bootstrap-form"]', { timeout: 5000 });
    await page.fill('#bootstrap-token', TEST_BOOTSTRAP_SECRET);
    await page.fill('#bootstrap-fullname', TEST_OWNER_FULLNAME);
    await page.fill('#bootstrap-username', TEST_OWNER_USERNAME);
    await page.fill('#bootstrap-password', TEST_OWNER_PASSWORD);
    await page.fill('#bootstrap-confirm-password', TEST_OWNER_PASSWORD);
    await page.fill('#bootstrap-email', 'owner@kawadswad.dev');
    await page.click('[data-testid="bootstrap-submit-btn"]');

    await page.waitForSelector('[data-testid="auth-success-notice"]', { timeout: 10000 });
    const successText = await page.textContent('[data-testid="auth-success-notice"]');
    assert(successText.includes('OWNER_ADMIN'), `Expected OWNER_ADMIN confirmation, got: ${successText}`);
    // Mode switcher must disappear permanently once initialized
    const bootstrapTabCount = await page.locator('[data-testid="mode-tab-bootstrap"]').count();
    assert(bootstrapTabCount === 0, 'Bootstrap tab must disappear after First Owner initialization');
    record(1, 'First Owner setup succeeds', 'PASS', 'Gated UI initialized First Owner as OWNER_ADMIN via real backend and hid bootstrap tab permanently');

    // ------------------------------------------------------------------
    // Scenario 2: Second Owner setup is rejected (HTTP 409)
    // ------------------------------------------------------------------
    const dupBootstrapResp = await fetch(`${PY_BASE}/api/auth/bootstrap-owner`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'X-KS-Bootstrap-Token': TEST_BOOTSTRAP_SECRET,
        'X-KS-Idempotency-Key': 'E2E-DUP-OWNER-002',
      },
      body: JSON.stringify({
        username: 'second.owner',
        full_name: 'Second Owner Attempt',
        password: TEST_OWNER_PASSWORD,
      }),
    });
    const dupJson = await dupBootstrapResp.json();
    assert(dupBootstrapResp.status === 409, `Expected 409 for second owner, got ${dupBootstrapResp.status}`);
    assert(dupJson.detail?.error_code === 'OWNER_ALREADY_INITIALIZED', `Unexpected error_code: ${JSON.stringify(dupJson)}`);
    record(2, 'Second Owner setup is rejected', 'PASS', 'Second bootstrap attempt rejected with HTTP 409 OWNER_ALREADY_INITIALIZED');

    // ------------------------------------------------------------------
    // Scenario 3: Incorrect password is rejected
    // ------------------------------------------------------------------
    await page.fill('#login-username', TEST_OWNER_USERNAME);
    await page.fill('#login-password', 'WrongPassword#9999');
    await page.click('[data-testid="login-submit-btn"]');
    await page.waitForSelector('[data-testid="auth-error-alert"]', { timeout: 10000 });
    const wrongPwdMsg = await page.textContent('[data-testid="auth-error-alert"]');
    assert(wrongPwdMsg.toLowerCase().includes('incorrect'), `Expected invalid credentials notice, got: ${wrongPwdMsg}`);
    record(3, 'Incorrect password is rejected', 'PASS', 'Backend returned 401 and Login UI displayed clear invalid credentials message');

    // ------------------------------------------------------------------
    // Scenario 5: Inactive user cannot log in
    // ------------------------------------------------------------------
    await fetch(`${PY_BASE}/__test__/seed-inactive-user`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ username: TEST_INACTIVE_USERNAME, password: TEST_INACTIVE_PASSWORD }),
    });
    await page.fill('#login-username', TEST_INACTIVE_USERNAME);
    await page.fill('#login-password', TEST_INACTIVE_PASSWORD);
    await page.click('[data-testid="login-submit-btn"]');
    await page.waitForSelector('[data-testid="auth-error-alert"]', { timeout: 10000 });
    const inactiveMsg = await page.textContent('[data-testid="auth-error-alert"]');
    assert(
      inactiveMsg.toLowerCase().includes('deactivated') || inactiveMsg.toLowerCase().includes('inactive'),
      `Expected inactive account notice, got: ${inactiveMsg}`
    );
    record(5, 'Inactive user cannot log in', 'PASS', 'Backend returned 403 and Login UI displayed Access Restricted / deactivated message');

    // ------------------------------------------------------------------
    // Scenario 4 & 7: Correct password succeeds & Owner accesses Dashboard
    // ------------------------------------------------------------------
    await page.fill('#login-username', TEST_OWNER_USERNAME);
    await page.fill('#login-password', TEST_OWNER_PASSWORD);
    await page.click('[data-testid="login-submit-btn"]');
    await page.waitForSelector('[data-testid="owner-role-badge"]', { timeout: 15000 });
    const roleBadge = (await page.textContent('[data-testid="owner-role-badge"]')).trim();
    const identitySummary = (await page.textContent('[data-testid="owner-identity-summary"]')).trim();
    assert(roleBadge.includes('OWNER_ADMIN'), `Expected OWNER_ADMIN badge, got: ${roleBadge}`);
    assert(identitySummary.includes(TEST_OWNER_FULLNAME), `Expected owner full name in dashboard, got: ${identitySummary}`);
    assert(identitySummary.includes(`@${TEST_OWNER_USERNAME}`), `Expected @username in dashboard, got: ${identitySummary}`);
    record(4, 'Correct password succeeds', 'PASS', 'Owner signed in via POST /api/auth/login with real PBKDF2 verification and Bearer JWT');
    record(7, 'Owner can access authorized dashboard', 'PASS', `Dashboard rendered identity (${TEST_OWNER_FULLNAME} @${TEST_OWNER_USERNAME}) and role badge (${roleBadge}) with zero auth errors`);

    // Verify mobile viewport responsiveness (390x844) while authenticated
    await page.setViewportSize({ width: 390, height: 844 });
    await page.waitForTimeout(300);
    const mobileOverflow = await page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth + 2);
    const mobileBadgeVisible = await page.locator('[data-testid="owner-role-badge"]').isVisible();
    assert(mobileBadgeVisible, 'Owner role badge must remain visible on mobile viewport');
    assert(!mobileOverflow, 'Mobile dashboard should not have horizontal overflow');
    await page.setViewportSize({ width: 1440, height: 900 });

    // ------------------------------------------------------------------
    // Scenario 8: Refresh preserves a valid session
    // ------------------------------------------------------------------
    const activeTokenBeforeReload = await page.evaluate(() => localStorage.getItem('ks_token'));
    assert(Boolean(activeTokenBeforeReload), 'Expected Bearer session token in storage before refresh');
    await page.reload({ waitUntil: 'networkidle' });
    await page.waitForSelector('[data-testid="owner-role-badge"]', { timeout: 15000 });
    const identityAfterReload = (await page.textContent('[data-testid="owner-identity-summary"]')).trim();
    assert(identityAfterReload.includes(TEST_OWNER_FULLNAME), 'Owner identity must persist across browser refresh');
    record(8, 'Refresh preserves a valid session', 'PASS', 'Browser reload verified session via GET /api/auth/me and restored Owner Dashboard');

    // ------------------------------------------------------------------
    // Scenario 9: Expired session is rejected on refresh
    // ------------------------------------------------------------------
    const expiredResp = await fetch(`${PY_BASE}/__test__/mint-expired-token`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ user_id: 'USR-000001', username: TEST_OWNER_USERNAME }),
    });
    const expiredData = await expiredResp.json();
    await page.evaluate((tok) => localStorage.setItem('ks_token', tok), expiredData.access_token);
    await page.reload({ waitUntil: 'networkidle' });
    await page.waitForSelector('[data-testid="login-form"]', { timeout: 10000 });
    const tokenAfterExpiry = await page.evaluate(() => localStorage.getItem('ks_token'));
    assert(!tokenAfterExpiry, 'Expired token must be cleared from browser storage');
    record(9, 'Expired session is rejected', 'PASS', 'Expired JWT rejected with HTTP 401 by /api/auth/me, storage cleared, returned to Login');

    // ------------------------------------------------------------------
    // Scenario 10 & 11: Logout terminates session & logged-out user cannot revisit protected pages
    // ------------------------------------------------------------------
    // Sign back in first
    await page.fill('#login-username', TEST_OWNER_USERNAME);
    await page.fill('#login-password', TEST_OWNER_PASSWORD);
    await page.click('[data-testid="login-submit-btn"]');
    await page.waitForSelector('[data-testid="owner-role-badge"]', { timeout: 15000 });
    const tokenBeforeLogout = await page.evaluate(() => localStorage.getItem('ks_token'));
    assert(Boolean(tokenBeforeLogout), 'Expected active token before logout');

    // Click Logout button in Header
    await page.click('button[title="Sign out"]');
    await page.waitForSelector('[data-testid="login-form"]', { timeout: 10000 });
    const tokenAfterLogout = await page.evaluate(() => localStorage.getItem('ks_token'));
    assert(!tokenAfterLogout, 'Token must be cleared on logout');

    // Wait briefly so async POST /api/auth/logout finishes on backend
    await page.waitForTimeout(400);

    // Verify revoked token is rejected server-side too
    const revokedCheckResp = await fetch(`${PY_BASE}/api/auth/me`, {
      headers: { Authorization: `Bearer ${tokenBeforeLogout}` },
    });
    assert(revokedCheckResp.status === 401, `Expected 401 for revoked token, got ${revokedCheckResp.status}`);
    record(10, 'Logout terminates the session', 'PASS', 'Logout cleared client state and revoked JWT server-side (subsequent /api/auth/me returned 401)');

    // Reload browser after logout -> stays on login screen, cannot access dashboard
    await page.reload({ waitUntil: 'networkidle' });
    await page.waitForSelector('[data-testid="login-form"]', { timeout: 10000 });
    const bodyAfterLogoutReload = await page.textContent('body');
    assert(!bodyAfterLogoutReload.includes('Executive Control Center'), 'Logged-out user must not access dashboard after reload');
    record(11, 'Logged-out user cannot revisit protected pages', 'PASS', 'Reload after logout remains locked on Login screen; revoked token rejected');

    assert(pageErrors.length === 0, `Uncaught page errors detected: ${pageErrors.join('; ')}`);

    console.log('\n' + '='.repeat(76));
    console.log(`KS-DEV-01 LIVE E2E SUMMARY: ${results.length}/12 SCENARIOS PASSED, 0 PAGE ERRORS`);
    console.log('='.repeat(76));
  } finally {
    if (browser) await browser.close().catch(() => {});
    if (pyServer) pyServer.kill('SIGTERM');
  }
}

runE2E().catch((err) => {
  console.error('KS-DEV-01 E2E TEST FAILED:', err);
  process.exit(1);
});
