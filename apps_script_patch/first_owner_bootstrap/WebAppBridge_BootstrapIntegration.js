/**
 * Kawad Swad ERP — Apps Script Isolated Development Module (Reconciled Draft — NOT MERGE-READY)
 * File: WebAppBridge_BootstrapIntegration.js
 *
 * Status:
 *   ISOLATED SOURCE PACKAGE ONLY. NOT VERIFIED FOR LIVE MERGE because the raw bound
 *   Apps Script archive (`Kawad_Swad_Bound_Apps_Script_Source_READONLY.zip`) is not yet
 *   available in this workspace.
 *
 * Purpose:
 *   Provides the hardened mandatory HMAC-SHA256 verification and closed `BOOTSTRAP_FIRST_OWNER`
 *   dispatch hook for `WebAppBridge.js`, addressing Mission 51B-1R-E2D Critical C1 (optional HMAC
 *   bypass) and aligning byte-for-byte with FastAPI `backend/app/apps_script_bridge.py`.
 *
 * Byte-for-Byte Signed Envelope Contract (`backend/app/apps_script_bridge.py:2818-2829`):
 *   Python computes:
 *     canonical_body = json.dumps(envelope, separators=(",", ":"), sort_keys=True, ensure_ascii=True, default=str)
 *     signature = hmac.new(secret.encode("utf-8"), canonical_body.encode("utf-8"), hashlib.sha256).hexdigest()
 *   Because `ensure_ascii=True` emits strictly 7-bit printable ASCII characters (`0x20..0x7E`),
 *   `canonical_body.encode("utf-8")` in Python and `Utilities.computeHmacSha256Signature(
 *   outer.canonical_envelope, sharedSecret, Utilities.Charset.UTF_8)` in Apps Script V8 hash the
 *   exact same byte sequence without any JSON key-order or Unicode normalization drift.
 *
 * Script Property Alignment:
 *   Mission 51B-1R-E2D §3.1 documents that bound `WebAppBridge.js` reads Script Property
 *   `SALES_APPS_SCRIPT_SHARED_SECRET` (>= 32 chars). Confirm against raw `WebAppBridge.js`
 *   once `Kawad_Swad_Bound_Apps_Script_Source_READONLY.zip` is supplied.
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
 * Emit a JSON TextOutput response for Web App `doPost(e)`.
 *
 * @param {Object} payloadObj
 * @return {GoogleAppsScript.Content.TextOutput}
 */
function ksJsonOutput_(payloadObj) {
  return ContentService
    .createTextOutput(JSON.stringify(payloadObj))
    .setMimeType(ContentService.MimeType.JSON);
}

/**
 * Verify mandatory contract_version, HMAC-SHA256 signature over exact `canonical_envelope` bytes,
 * outer-vs-signed field consistency, and ±300s timestamp freshness window.
 * Fails closed on any missing, weak, malformed, unknown-version, expired, or forged request.
 *
 * @param {Object} e Apps Script doPost event object
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
        error_code: 'BRIDGE_SHARED_SECRET_NOT_CONFIGURED',
        message: 'Apps Script HMAC shared secret is missing or below minimum 32-char length.',
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
        error_code: 'EMPTY_REQUEST_BODY',
        message: 'Request body is required.',
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
        error_code: 'INVALID_HMAC_SIGNATURE',
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
 * Closed action dispatch hook to integrate inside existing `WebAppBridge.js` `doPost(e)`.
 *
 * IMPORTANT — PRE-MERGE INTEGRATION REQUIREMENT:
 *   Per Mission 51B-1R-E2D §3.4–3.6, the bound `WebAppBridge.js` currently:
 *     - skips HMAC when signature is absent (Critical C1),
 *     - uses nonce-only lookup `ksFindByNonce_` before routing (High H4),
 *     - falls through unknown actions to generic `ksWriteCanonicalRowByHeaders_` (High H2/H3).
 *   When merging into the real `WebAppBridge.js` (after raw ZIP inspection):
 *     1. Run `ksVerifySignedBridgeEnvelope_(e)` BEFORE any nonce lookup or sheet access.
 *     2. Route `BOOTSTRAP_FIRST_OWNER` directly to `ksBootstrapFirstOwner_(auth.envelope)`
 *        BEFORE legacy `ksFindByNonce_` / `ksRecordIdAllocation_` so bootstrap never uses
 *        the defective nonce-only lookup or generic fallback writer.
 *     3. Pass all other verified actions to the existing governed dispatcher (which itself
 *        must be hardened under Mission 51B-1R-E2G before production deployment).
 *
 * @param {Object} verifiedEnvelope
 * @param {Function=} existingDispatcher Existing bound action dispatcher from WebAppBridge.js
 * @return {Object}
 */
function ksRouteGovernedWriteWithBootstrap_(verifiedEnvelope, existingDispatcher) {
  var action = String((verifiedEnvelope && verifiedEnvelope.action) || '').trim().toUpperCase();
  var targetTab = String((verifiedEnvelope && verifiedEnvelope.target_tab) || '').trim();

  if (action === 'BOOTSTRAP_FIRST_OWNER') {
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

  if (typeof existingDispatcher === 'function') {
    return existingDispatcher(verifiedEnvelope);
  }

  return ksBootstrapResponse_(verifiedEnvelope, 'REJECTED', {
    error_code: 'UNREGISTERED_GOVERNED_ACTION',
    message: 'Governed action is not registered on this WebAppBridge route.',
    http_status: 403,
    retryable: false
  });
}
