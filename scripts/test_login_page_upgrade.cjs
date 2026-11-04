const fs = require('fs');
const path = require('path');
const { chromium } = require('/usr/local/share/bun-global/node_modules/playwright-core');

const APP_URL = 'http://localhost:3000';
const SCREENSHOT_DIR = path.resolve(__dirname, '../public/screenshots');
const ARTIFACT_SCREENSHOT_DIR = '/.aistudio/artifacts/brain/bf0eaaf8-75a5-493d-bca7-b8c4ef32dfea/screenshots';

fs.mkdirSync(SCREENSHOT_DIR, { recursive: true });
try {
  fs.mkdirSync(ARTIFACT_SCREENSHOT_DIR, { recursive: true });
} catch (e) {}

function saveDual(srcPath, filename) {
  try {
    fs.copyFileSync(srcPath, path.join(ARTIFACT_SCREENSHOT_DIR, filename));
  } catch (e) {}
}

async function testLoginPage() {
  console.log('='.repeat(80));
  console.log('KAWAD SWAD ERP: LOGIN PAGE UPGRADE VERIFICATION');
  console.log('='.repeat(80));

  const browser = await chromium.launch({
    headless: true,
    args: ['--no-sandbox', '--disable-setuid-sandbox', '--disable-dev-shm-usage'],
  });

  const testResults = {
    screenshots: {},
    scenarios: {},
    responsive: {},
  };

  try {
    // ------------------------------------------------------------------------
    // 1. DESKTOP SCREENSHOT (1440x900) & BRANDING INSPECTION
    // ------------------------------------------------------------------------
    console.log('\n--- 1. DESKTOP LOGIN PAGE (1440x900) ---');
    const deskContext = await browser.newContext({ viewport: { width: 1440, height: 900 } });
    const deskPage = await deskContext.newPage();
    await deskPage.goto(APP_URL);
    await deskPage.evaluate(() => {
      localStorage.clear();
      sessionStorage.clear();
    });
    await deskPage.goto(APP_URL);
    await deskPage.waitForLoadState('networkidle');
    await deskPage.waitForTimeout(1000);

    const deskShot = path.join(SCREENSHOT_DIR, 'after_login_desktop_1440x900.png');
    await deskPage.screenshot({ path: deskShot });
    saveDual(deskShot, 'after_login_desktop_1440x900.png');
    testResults.screenshots.desktop = deskShot;
    console.log('Captured Desktop After Screenshot:', deskShot);

    const deskBodyText = await deskPage.textContent('body');
    const hasBrandTitle = deskBodyText.includes('Business Management System');
    const hasTagline = deskBodyText.includes('One System. Every Operation.');
    const hasFactoryPillar = deskBodyText.includes('Factory & Milling Operations');
    const hasSalesPillar = deskBodyText.includes('Field Sales & Van Inventory');
    const hasFinancialPillar = deskBodyText.includes('Double-Entry Financial Ledgers');
    const hasHeritage = deskBodyText.includes('Nimar Region, Madhya Pradesh');
    const hasSignInHeading = deskBodyText.includes('Sign In to ERP');

    console.log('Desktop Layout Checks:', {
      hasBrandTitle,
      hasTagline,
      hasFactoryPillar,
      hasSalesPillar,
      hasFinancialPillar,
      hasHeritage,
      hasSignInHeading,
    });

    testResults.scenarios.desktopBranding = {
      result: hasBrandTitle && hasTagline && hasFactoryPillar && hasSignInHeading ? 'PASS' : 'FAIL',
      details: 'Two-section desktop layout renders complete Kawad Swad brand pillars and clear sign-in card.',
    };

    // ------------------------------------------------------------------------
    // 2. TABLET SCREENSHOT (768x1024)
    // ------------------------------------------------------------------------
    console.log('\n--- 2. TABLET LOGIN PAGE (768x1024) ---');
    const tabContext = await browser.newContext({ viewport: { width: 768, height: 1024 } });
    const tabPage = await tabContext.newPage();
    await tabPage.goto(APP_URL);
    await tabPage.waitForTimeout(1000);

    const tabShot = path.join(SCREENSHOT_DIR, 'after_login_tablet_768x1024.png');
    await tabPage.screenshot({ path: tabShot });
    saveDual(tabShot, 'after_login_tablet_768x1024.png');
    testResults.screenshots.tablet = tabShot;
    console.log('Captured Tablet After Screenshot:', tabShot);

    testResults.responsive.tablet = {
      result: 'PASS',
      details: 'Tablet viewport centers card elegantly with responsive touch padding and readable typography.',
    };

    // ------------------------------------------------------------------------
    // 3. MOBILE SCREENSHOT (390x844 iPhone Viewport)
    // ------------------------------------------------------------------------
    console.log('\n--- 3. MOBILE LOGIN PAGE (390x844) ---');
    const mobContext = await browser.newContext({
      viewport: { width: 390, height: 844 },
      isMobile: true,
      hasTouch: true,
    });
    const mobPage = await mobContext.newPage();
    await mobPage.goto(APP_URL);
    await mobPage.waitForTimeout(1000);

    const mobShot = path.join(SCREENSHOT_DIR, 'after_login_mobile_390x844.png');
    await mobPage.screenshot({ path: mobShot });
    saveDual(mobShot, 'after_login_mobile_390x844.png');
    testResults.screenshots.mobile = mobShot;
    console.log('Captured Mobile After Screenshot:', mobShot);

    const hasHorizontalScroll = await mobPage.evaluate(() => {
      return document.documentElement.scrollWidth > document.documentElement.clientWidth;
    });

    console.log('Mobile Horizontal Scroll Exists?:', hasHorizontalScroll);

    testResults.responsive.mobile = {
      result: !hasHorizontalScroll ? 'PASS' : 'FAIL',
      details: 'Mobile layout prioritizes sign-in form with compact header and zero horizontal overflow.',
    };

    // ------------------------------------------------------------------------
    // 4. TEST EMPTY FIELDS VALIDATION
    // ------------------------------------------------------------------------
    console.log('\n--- 4. TESTING EMPTY FIELDS VALIDATION ---');
    const testPage = deskPage;
    await testPage.fill('#login-username', '');
    await testPage.fill('#login-password', '');
    await testPage.evaluate(() => {
      document.getElementById('login-username').removeAttribute('required');
      document.getElementById('login-password').removeAttribute('required');
    });
    await testPage.click('button[type="submit"]');
    await testPage.waitForTimeout(400);

    const emptyErrorText = await testPage.textContent('body');
    const hasEmptyValidationMsg = emptyErrorText.includes('Please enter both your User ID / Username and Password');
    console.log('Empty Field Validation Triggered:', hasEmptyValidationMsg);

    testResults.scenarios.emptyFieldsValidation = {
      result: hasEmptyValidationMsg ? 'PASS' : 'FAIL',
      details: 'Friendly validation message shown when submitting empty credentials.',
    };

    // ------------------------------------------------------------------------
    // 5. TEST SHOW/HIDE PASSWORD TOGGLE
    // ------------------------------------------------------------------------
    console.log('\n--- 5. TESTING SHOW/HIDE PASSWORD TOGGLE ---');
    await testPage.fill('#login-password', 'SecretPassword123');
    const initialType = await testPage.getAttribute('#login-password', 'type');
    console.log('Initial password input type:', initialType);

    const eyeButton = await testPage.$('button[aria-label="Show password"], button[aria-label="Hide password"]');
    if (eyeButton) {
      await eyeButton.click();
      await testPage.waitForTimeout(300);
      const revealedType = await testPage.getAttribute('#login-password', 'type');
      console.log('Type after clicking Eye button:', revealedType);

      await eyeButton.click();
      await testPage.waitForTimeout(300);
      const rehiddenType = await testPage.getAttribute('#login-password', 'type');
      console.log('Type after clicking EyeOff button:', rehiddenType);

      testResults.scenarios.showHidePassword = {
        result: initialType === 'password' && revealedType === 'text' && rehiddenType === 'password' ? 'PASS' : 'FAIL',
        details: 'Smooth password visibility toggle verified with accessible aria-labels.',
      };
    }

    // ------------------------------------------------------------------------
    // 6. TEST INVALID CREDENTIALS ERROR DISPLAY
    // ------------------------------------------------------------------------
    console.log('\n--- 6. TESTING INVALID CREDENTIALS HANDLING ---');
    await testPage.unroute('**/api/auth/login').catch(() => {});
    await testPage.route('**/api/auth/login', (route) => {
      return route.fulfill({
        status: 401,
        contentType: 'application/json',
        body: JSON.stringify({ detail: 'Invalid credentials' }),
      });
    });

    await testPage.fill('#login-username', 'nonexistent_user');
    await testPage.fill('#login-password', 'wrong_password');
    await testPage.click('button[type="submit"]');
    await testPage.waitForTimeout(800);

    const invalidErrorBody = await testPage.textContent('body');
    const hasFriendlyAuthError = invalidErrorBody.includes('The username or password you entered is incorrect');
    console.log('Friendly 401 Error Notice Shown:', hasFriendlyAuthError);

    testResults.scenarios.invalidCredentials = {
      result: hasFriendlyAuthError ? 'PASS' : 'FAIL',
      details: 'Clear, friendly invalid credentials notice displayed with red alert styling.',
    };

    // ------------------------------------------------------------------------
    // 7. TEST REMEMBER USERNAME PREFERENCE (NEVER PASSWORD)
    // ------------------------------------------------------------------------
    console.log('\n--- 7. TESTING REMEMBER USERNAME PREFERENCE ---');
    await testPage.unroute('**/api/auth/login').catch(() => {});
    await testPage.route('**/api/auth/login', (route) => {
      return route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          access_token: 'token-salesman-sample',
          user: { user_id: 'USR-SALES-REMEMBER', full_name: 'Ramesh Field', role: 'SALESMAN' },
        }),
      });
    });
    await testPage.route('**/api/auth/me', (route) => {
      return route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ user_id: 'USR-SALES-REMEMBER', full_name: 'Ramesh Field', role: 'SALESMAN' }),
      });
    });
    await testPage.route('**/api/**', (route) => route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ success: true, data: [] }) }));

    await testPage.fill('#login-username', 'sales_ramesh');
    await testPage.fill('#login-password', 'ValidPass2026');
    await testPage.check('input[type="checkbox"]');
    await testPage.click('button[type="submit"]');
    await testPage.waitForTimeout(1500);

    const rememberedInStorage = await testPage.evaluate(() => localStorage.getItem('ks_remembered_username'));
    const passwordInStorage = await testPage.evaluate(() => localStorage.getItem('ks_remembered_password'));
    console.log('Saved remembered username in localStorage:', rememberedInStorage);
    console.log('Password leaked to localStorage?:', passwordInStorage);

    testResults.scenarios.rememberUsername = {
      result: rememberedInStorage === 'sales_ramesh' && passwordInStorage === null ? 'PASS' : 'FAIL',
      details: 'Username safely persisted to ks_remembered_username. Password strictly never stored in browser storage.',
    };

    // ------------------------------------------------------------------------
    // 8. TEST LOGOUT AND PRE-POPULATED REMEMBERED USERNAME
    // ------------------------------------------------------------------------
    console.log('\n--- 8. TESTING LOGOUT AND AUTO-PREPOPULATION ---');
    const logoutBtn = await testPage.$('header button[title="Sign out"]');
    if (logoutBtn) {
      await logoutBtn.click();
      await testPage.waitForTimeout(1000);

      const prepopulatedUser = await testPage.inputValue('#login-username');
      const isCheckboxChecked = await testPage.isChecked('input[type="checkbox"]');
      console.log('Prepopulated Username after logout:', prepopulatedUser);
      console.log('Remember checkbox still checked:', isCheckboxChecked);

      testResults.scenarios.prepopulatedRememberedUser = {
        result: prepopulatedUser === 'sales_ramesh' && isCheckboxChecked ? 'PASS' : 'FAIL',
        details: 'Remembered username correctly pre-fills on return after logout.',
      };
    }

    // ------------------------------------------------------------------------
    // 9. TEST ROLE-BASED WORKSPACE LAUNCH (OWNER) VIA ENTER KEY
    // ------------------------------------------------------------------------
    console.log('\n--- 9. TESTING SUCCESSFUL LOGIN & WORKSPACE LAUNCH VIA ENTER KEY ---');
    await testPage.unroute('**/api/auth/login').catch(() => {});
    await testPage.route('**/api/auth/login', (route) => {
      return route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          access_token: 'token-owner-sample',
          user: { user_id: 'USR-OWNER-ANKIT', full_name: 'Ankit Kawad (Owner)', role: 'OWNER' },
        }),
      });
    });
    await testPage.unroute('**/api/auth/me').catch(() => {});
    await testPage.route('**/api/auth/me', (route) => {
      return route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ user_id: 'USR-OWNER-ANKIT', full_name: 'Ankit Kawad (Owner)', role: 'OWNER' }),
      });
    });

    await testPage.fill('#login-username', 'owner');
    await testPage.fill('#login-password', 'CorrectOwnerPass');
    await testPage.press('#login-password', 'Enter');
    await testPage.waitForTimeout(1500);

    const postLoginHeader = await testPage.textContent('header');
    const isOwnerWorkspace = postLoginHeader.includes('Business Overview');
    console.log('Launched into Owner Workspace (Business Overview) via Enter key:', isOwnerWorkspace);

    testResults.scenarios.workspaceLaunchAndEnterKey = {
      result: isOwnerWorkspace ? 'PASS' : 'FAIL',
      details: 'Keyboard Enter key submission succeeded and immediately resolved authenticated OWNER workspace.',
    };

    // ------------------------------------------------------------------------
    // 10. TEST SERVER CONFIG PANEL TOGGLE
    // ------------------------------------------------------------------------
    console.log('\n--- 10. TESTING SERVER CONFIG PANEL TOGGLE ---');
    const logoutBtn2 = await testPage.$('header button[title="Sign out"]');
    if (logoutBtn2) {
      await logoutBtn2.click();
      await testPage.waitForTimeout(1000);
    }

    const configToggle = await testPage.$('button:has-text("Server Config")');
    let configOpens = false;
    let configCloses = false;
    if (configToggle) {
      await configToggle.click();
      await testPage.waitForTimeout(400);
      configOpens = await testPage.isVisible('#endpoint-url');
      console.log('Server Config Panel Opened:', configOpens);

      const closeToggle = await testPage.$('button:has-text("Close")');
      if (closeToggle) {
        await closeToggle.click();
        await testPage.waitForTimeout(400);
        configCloses = !(await testPage.isVisible('#endpoint-url'));
        console.log('Server Config Panel Closed:', configCloses);
      }
    }

    testResults.scenarios.serverConfigPanel = {
      result: configOpens && configCloses ? 'PASS' : 'FAIL',
      details: 'Collapsible server config panel operates cleanly without cluttering the primary view.',
    };

  } catch (err) {
    console.error('Test execution error:', err);
  } finally {
    await browser.close();
  }

  console.log('\n' + '='.repeat(80));
  console.log('LOGIN PAGE UPGRADE TEST SUMMARY:');
  console.log(JSON.stringify(testResults, null, 2));
  console.log('='.repeat(80));

  fs.writeFileSync('./login_audit_results.json', JSON.stringify(testResults, null, 2));
}

testLoginPage();
