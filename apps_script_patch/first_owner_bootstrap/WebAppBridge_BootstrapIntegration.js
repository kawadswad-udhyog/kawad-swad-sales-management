/**
 * Kawad Swad ERP — Apps Script Isolated Development Module (Source-Reconciled — NOT YET MERGED)
 * File: WebAppBridge_BootstrapIntegration.js
 *
 * Status:
 *   ISOLATED SOURCE PACKAGE — RECONCILED AGAINST VERBATIM `WebAppBridge.js` (42/43, SHA-256
 *   `3c1e85e895fe5e685970a86586531bba7ee90aab5d2d108a8fefd971ab828287`, export lines 13912–14193).
 *   NOT MERGED into the live Apps Script project; no execution or deployment performed.
 *
 * Verified Exact Defects in Current Bound `WebAppBridge.js` Addressed Here:
 *   1. `WebAppBridge.js:34-49` (export lines 13949–13964):
 *      - HMAC check is wrapped in `if (providedSig) { ... }` (E2D Critical C1: unsigned requests bypass HMAC).
 *      - Computes `ksHmacSha256Hex_(rawBody, sharedSecret)` even when `providedSig` came from `req.signature`
 *        inside `rawBody` (self-referential JSON signature impossibility).
 *   2. `WebAppBridge.js:71-114` (export lines 13986–14029):
 *      - Runs nonce-only `ksFindByNonce_(nonce)` (E2D High H4) without action/tab/payload_hash verification.
 *      - Appends a second `ALLOC-<Date.now()>` row via `ksRecordIdAllocation_` (`WebAppBridge.js:91`,
 *        export line 14006) — which would DUPLICATE `IdAllocations` if `BOOTSTRAP_FIRST_OWNER` fell through
 *        after calling `ksAllocateId`.
 *      - Calls `ksLogAudit_` (`WebAppBridge.js:93`, export line 14008) — which would DUPLICATE `AuditLog`.
 *      - Always wraps the response as `status: 'CONFIRMED'` (`WebAppBridge.js:106`, export line 14021),
 *        which would mask `REJECTED` or `RECOVERY_REQUIRED` bootstrap states!
 *
 * Verified Exact Safe Integration Point Inside Bound `WebAppBridge.js` `doPost(e)`:
 *   - REPLACE `WebAppBridge.js:9-50` (export lines 13924–13965) with:
 *       const auth = ksVerifySignedBridgeEnvelope_(e);
 *       if (!auth.ok) {
 *         return ksBridgeJson_(auth.errorResponse);
 *       }
 *       const req = auth.envelope;
 *   - KEEP `WebAppBridge.js:51-69` (export lines 13966–13984) parsing `action`, `targetTab`, `nonce`,
 *     `correlationId`, `actorUserId`, `actorRole`, `payload` and checking required envelope fields.
 *   - INSERT IMMEDIATELY BEFORE `WebAppBridge.js:71` (export line 13986 `// 2. Serialize via ScriptLock`):
 *       if (action === 'BOOTSTRAP_FIRST_OWNER') {
 *         return ksBridgeJson_(ksDispatchBootstrapFirstOwner_(req));
 *       }
 *   - PRESERVE `WebAppBridge.js:71-124` (export lines 13986–14039) untouched for all other existing
 *     governed actions (note: full Mission 51B-1R-E2G remediation of H1–H9 for ordinary actions
 *     remains a separate workstream).
 *
 * Verified Compatibility:
 *   - Script Property name matches verbatim `WebAppBridge.js:22` (export line 13937):
 *     `SALES_APPS_SCRIPT_SHARED_SECRET` (>= 32 chars).
 *   - FastAPI `backend/app/apps_script_bridge.py:2818-2829` ALREADY transmits `wire_envelope` with
 *     `contract_version: "2.0"`, `signature_alg: "HMAC-SHA-256"`, `signature`, and ASCII-escaped
 *     `canonical_envelope` for ALL governed bridge actions (not only bootstrap), so mandatory HMAC
 *     verification is 100% compatible with every existing FastAPI governed action.
 *   - Zero symbol collisions with `WebAppBridge.js` (`ksBridgeJson_`, `ksHmacSha256Hex_`, `ksSafeEqual_`)
 *     or any of the other 39 `.js` files in the bound project.
 */

var KS_BRIDGE_SHARED_SECRET_PROP = 'SALES_APPS_SCRIPT_SHARED_SECRET';
var KS_BRIDGE_SUPPORTED_CONTRACT_VERSION = '2.0';
var KS_BRIDGE_SUPPORTED_SIGNATURE_ALG = 'HMAC-SHA-256';
var KS_BRIDGE_MAX_SKEW_SECONDS = 300;

/**
 * Compute lowercase hexadecimal HMAC-SHA256 signature using explicit UTF-8 encoding
 * matching Python `hmac.new(secret.encode("utf-8"), raw_body.encode("utf-8"), hashlib.sha256).hexdigest()`.
 *
 * @param {string} messageUtf8
 * @param {string} secretUtf8
 * @return {string}
 */
function ksComputeHmacSha256Hex_(messageUtf8, secretUtf8) {
  var sigBytes = Utilities.computeHmacSha256Signature(
    String(messageUtf8 || ''),
    String(secretUtf8 || ''),
    Utilities.Charset.UTF_8
  );
  var hex = [];
  for (var i = 0; i < sigBytes.length; i++) {
    var b = sigBytes[i];
    if (b < 0) {
      b += 256;
    }
    var part = b.toString(16);
    hex.push(part.length === 1 ? '0' + part : part);
  }
  return hex.join('');
}

/**
 * Verify mandatory `contract_version = "2.0"`, `signature_alg = "HMAC-SHA-256"`,
 * HMAC-SHA256 signature over exact `canonical_envelope` bytes, outer-vs-signed field consistency,
 * and ±300s timestamp freshness window.
 *
 * Fails closed on any missing, weak, malformed, unknown-version, expired, tampered, or forged request.
 *
 * @param {Object} e Apps Script `doPost(e)` event object
 * @return {{ok: boolean, envelope?: Object, errorResponse?: Object}}
 */
function ksVerifySignedBridgeEnvelope_(e) {
  var props = PropertiesService.getScriptProperties();
  var sharedSecret = String(props.getProperty(KS_BRIDGE_SHARED_SECRET_PROP) || '').trim();
  if (sharedSecret.length < 32) {
    return {
      ok: false,
      errorResponse: {
        status: 'REJECTED',
        error_code: 'BRIDGE_NOT_CONFIGURED',
        message: 'SALES_APPS_SCRIPT_SHARED_SECRET missing or < 32 chars in ScriptProperties.',
        http_status: 503,
        retryable: false
      }
    };
  }

  var rawBody = e && e.postData && typeof e.postData.contents === 'string'
    ? e.postData.contents
    : '';
  if (!rawBody) {
    return {
      ok: false,
      errorResponse: {
        status: 'REJECTED',
        error_code: 'EMPTY_PAYLOAD',
        message: 'Missing POST body.',
        http_status: 400,
        retryable: false
      }
    };
  }

  var outer;
  try {
    outer = JSON.parse(rawBody);
  } catch (parseErr) {
    return {
      ok: false,
      errorResponse: {
        status: 'REJECTED',
        error_code: 'INVALID_JSON_BODY',
        message: 'Malformed JSON request body.',
        http_status: 400,
        retryable: false
      }
    };
  }

  if (!outer || typeof outer !== 'object') {
    return {
      ok: false,
      errorResponse: {
        status: 'REJECTED',
        error_code: 'INVALID_JSON_BODY',
        message: 'JSON body must be an object.',
        http_status: 400,
        retryable: false
      }
    };
  }

  // Mission 51B-1R-E2F O-02: Unknown contract versions and algorithms must fail closed
  if (String(outer.contract_version || '').trim() !== KS_BRIDGE_SUPPORTED_CONTRACT_VERSION) {
    return {
      ok: false,
      errorResponse: {
        status: 'REJECTED',
        error_code: 'UNSUPPORTED_CONTRACT_VERSION',
        message: 'Unsupported or missing signed bridge contract_version.',
        http_status: 400,
        retryable: false
      }
    };
  }
  if (String(outer.signature_alg || '').trim().toUpperCase() !== KS_BRIDGE_SUPPORTED_SIGNATURE_ALG) {
    return {
      ok: false,
      errorResponse: {
        status: 'REJECTED',
        error_code: 'UNSUPPORTED_SIGNATURE_ALG',
        message: 'Unsupported or missing signature_alg (HMAC-SHA-256 required).',
        http_status: 400,
        retryable: false
      }
    };
  }

  if (
    typeof outer.canonical_envelope !== 'string' ||
    !outer.canonical_envelope ||
    typeof outer.signature !== 'string' ||
    !/^[0-9a-f]{64}$/i.test(outer.signature.trim())
  ) {
    return {
      ok: false,
      errorResponse: {
        status: 'REJECTED',
        error_code: 'MISSING_OR_MALFORMED_HMAC_ENVELOPE',
        message: 'Mandatory signed canonical_envelope and 64-hex HMAC-SHA256 signature are required.',
        http_status: 401,
        retryable: false
      }
    };
  }

  var expectedSig = ksComputeHmacSha256Hex_(outer.canonical_envelope, sharedSecret);
  var providedSig = outer.signature.trim().toLowerCase();
  if (!ksBootstrapSafeEqual_(providedSig, expectedSig)) {
    return {
      ok: false,
      errorResponse: {
        status: 'REJECTED',
        error_code: 'INVALID_SIGNATURE',
        message: 'HMAC-SHA256 signature verification failed.',
        http_status: 401,
        retryable: false
      }
    };
  }

  var envelope;
  try {
    envelope = JSON.parse(outer.canonical_envelope);
  } catch (envErr) {
    return {
      ok: false,
      errorResponse: {
        status: 'REJECTED',
        error_code: 'INVALID_CANONICAL_ENVELOPE',
        message: 'Signed canonical_envelope is not valid JSON.',
        http_status: 400,
        retryable: false
      }
    };
  }

  if (!envelope || typeof envelope !== 'object') {
    return {
      ok: false,
      errorResponse: {
        status: 'REJECTED',
        error_code: 'INVALID_CANONICAL_ENVELOPE',
        message: 'Signed canonical_envelope must decode to an object.',
        http_status: 400,
        retryable: false
      }
    };
  }

  // Defense-in-depth: reject if unsigned outer convenience fields disagree with signed canonical_envelope
  var checkedFields = ['action', 'target_tab', 'nonce', 'correlation_id', 'payload_hash'];
  for (var i = 0; i < checkedFields.length; i++) {
    var f = checkedFields[i];
    if (
      Object.prototype.hasOwnProperty.call(outer, f) &&
      String(outer[f] === null || outer[f] === undefined ? '' : outer[f]) !==
      String(envelope[f] === null || envelope[f] === undefined ? '' : envelope[f])
    ) {
      return {
        ok: false,
        errorResponse: {
          status: 'REJECTED',
          error_code: 'OUTER_ENVELOPE_TAMPER_DETECTED',
          message: 'Outer wire field disagreed with signed canonical_envelope (' + f + ').',
          http_status: 401,
          retryable: false
        }
      };
    }
  }

  // Enforce ±300s timestamp freshness window against replay of captured envelopes
  var tsRaw = String((envelope && envelope.timestamp) || '').trim();
  var tsMs = Date.parse(tsRaw);
  if (!tsRaw || isNaN(tsMs)) {
    return {
      ok: false,
      errorResponse: {
        status: 'REJECTED',
        error_code: 'INVALID_ENVELOPE_TIMESTAMP',
        message: 'Envelope timestamp must be a valid ISO-8601 UTC timestamp.',
        http_status: 401,
        retryable: false
      }
    };
  }
  var skewSec = Math.abs(Date.now() - tsMs) / 1000;
  if (skewSec > KS_BRIDGE_MAX_SKEW_SECONDS) {
    return {
      ok: false,
      errorResponse: {
        status: 'REJECTED',
        error_code: 'ENVELOPE_TIMESTAMP_SKEW_EXCEEDED',
        message: 'Envelope timestamp exceeds allowed +/-300 second window.',
        http_status: 401,
        retryable: false
      }
    };
  }

  return { ok: true, envelope: envelope };
}

/**
 * Isolated pre-lock dispatcher for `BOOTSTRAP_FIRST_OWNER`, called from `WebAppBridge.js` `doPost(e)`
 * immediately AFTER `ksVerifySignedBridgeEnvelope_(e)` and required envelope field validation,
 * and strictly BEFORE `WebAppBridge.js:71` (`lock.waitLock(20000)` / `ksFindByNonce_`).
 *
 * Ensures `BOOTSTRAP_FIRST_OWNER`:
 *   - NEVER hits defective nonce-only `ksFindByNonce_` (`WebAppBridge.js:73`, E2D H4),
 *   - NEVER falls through to `ksWriteCanonicalRowByHeaders_` (`WebAppBridge.js:165`, E2D H2/H3),
 *   - NEVER writes a duplicate `ALLOC-<Date.now()>` row via `ksRecordIdAllocation_` (`WebAppBridge.js:91`),
 *   - NEVER writes a duplicate unverified `AuditLog` row (`WebAppBridge.js:93`),
 *   - NEVER gets wrapped as `CONFIRMED` when returning `REJECTED` or `RECOVERY_REQUIRED`.
 *
 * @param {Object} verifiedEnvelope
 * @return {Object} Standardized bridge response ready for `ksBridgeJson_(...)`
 */
function ksDispatchBootstrapFirstOwner_(verifiedEnvelope) {
  var action = String((verifiedEnvelope && verifiedEnvelope.action) || '').trim().toUpperCase();
  var targetTab = String((verifiedEnvelope && verifiedEnvelope.target_tab) || '').trim();

  if (action !== 'BOOTSTRAP_FIRST_OWNER') {
    return ksBootstrapResponse_(verifiedEnvelope, 'REJECTED', {
      error_code: 'UNEXPECTED_BOOTSTRAP_DISPATCH',
      message: 'ksDispatchBootstrapFirstOwner_ only handles BOOTSTRAP_FIRST_OWNER.',
      http_status: 400,
      retryable: false
    });
  }

  if (targetTab !== 'Users') {
    return ksBootstrapResponse_(verifiedEnvelope, 'REJECTED', {
      error_code: 'INVALID_TARGET_TAB',
      message: 'BOOTSTRAP_FIRST_OWNER must target Users.',
      http_status: 422,
      retryable: false
    });
  }

  return ksBootstrapFirstOwner_(verifiedEnvelope);
}

/*
 * ============================================================================
 * EXACT SURGICAL MERGE PATCH FOR BOUND `WebAppBridge.js` `doPost(e)`
 * (Reference: verbatim `WebAppBridge.js:6-124`, export lines 13921–14039)
 * ============================================================================
 *
 *   function doPost(e) {
 *     const lock = LockService.getScriptLock();
 *     try {
 *       // 1. Mandatory HMAC-SHA256 + contract_version="2.0" + ±300s skew check
 *       //    (Replaces WebAppBridge.js lines 9–50 / export lines 13924–13965)
 *       const auth = ksVerifySignedBridgeEnvelope_(e);
 *       if (!auth.ok) {
 *         return ksBridgeJson_(auth.errorResponse);
 *       }
 *       const req = auth.envelope;
 *
 *       const action = String(req.action || '').trim().toUpperCase();
 *       const targetTab = String(req.target_tab || '').trim();
 *       const nonce = String(req.nonce || '').trim();
 *       const correlationId = String(req.correlation_id || '').trim();
 *       const actorUserId = String(req.actor_user_id || '').trim();
 *       const actorRole = String(req.actor_role || '').trim().toUpperCase();
 *       const payload = req.payload || {};
 *
 *       if (!action || !targetTab || !nonce || !correlationId) {
 *         return ksBridgeJson_({
 *           status: 'REJECTED',
 *           correlation_id: correlationId,
 *           nonce: nonce,
 *           action: action,
 *           target_tab: targetTab,
 *           error_code: 'MISSING_ENVELOPE_FIELDS',
 *           message: 'action, target_tab, nonce, and correlation_id are all required.'
 *         });
 *       }
 *
 *       // 1B. Isolated pre-lock route for BOOTSTRAP_FIRST_OWNER
 *       //     (Inserted strictly BEFORE WebAppBridge.js line 71 / export line 13986)
 *       if (action === 'BOOTSTRAP_FIRST_OWNER') {
 *         return ksBridgeJson_(ksDispatchBootstrapFirstOwner_(req));
 *       }
 *
 *       // 2..5. Existing governed action flow (WebAppBridge.js lines 71–124 unchanged)
 *       lock.waitLock(20000);
 *       ...
 *     } catch (err) {
 *       ...
 *     } finally {
 *       if (lock.hasLock()) lock.releaseLock();
 *     }
 *   }
 */
