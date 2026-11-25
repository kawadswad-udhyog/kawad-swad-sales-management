/**
 * Kawad Swad ERP — Apps Script Isolated Development Module
 * File: WebAppBridge_BootstrapIntegration.js
 *
 * Purpose:
 *   Provides the hardened HMAC-SHA256 verification and closed action dispatch integration
 *   for `WebAppBridge.js` to support `BOOTSTRAP_FIRST_OWNER` while closing Mission 51B-1R-E2D
 *   Defect D01 (mandatory signature authentication in `doPost(e)`).
 *
 * Wire Contract Alignment with FastAPI (`backend/app/apps_script_bridge.py`):
 *   Google Apps Script `doPost(e)` does not expose custom HTTP request headers
 *   (such as `X-KS-Signature`). FastAPI therefore sends a JSON body containing:
 *     {
 *       ...top-level envelope fields...,
 *       "contract_version": "2.0",
 *       "signature_alg": "HMAC-SHA-256",
 *       "signature": "<lowercase hex HMAC-SHA256 of canonical_envelope>",
 *       "canonical_envelope": "<exact UTF-8 JSON string signed by FastAPI>"
 *     }
 *
 *   Apps Script computes `HMAC-SHA256(canonical_envelope, KS_APPS_SCRIPT_SHARED_SECRET)`
 *   directly over the exact `canonical_envelope` string, compares it in constant time to
 *   `outer.signature`, enforces timestamp skew (`±300s`), and parses ONLY the verified
 *   `canonical_envelope` JSON before routing — eliminating Python/V8 serialization drift
 *   and guaranteeing zero unauthenticated mutations.
 *
 * IMPORTANT — PRE-MERGE VERIFICATION REQUIRED:
 *   Merge this logic into the bound project's `WebAppBridge.js` ONLY after inspecting the
 *   raw `Kawad_Swad_Bound_Apps_Script_Source_READONLY.zip` to preserve all existing
 *   governed action routes (`CREATE_SALE`, `CREATE_USER`, `POST_JOURNAL_VOUCHER`, etc.)
 *   and confirm the exact Script Property name holding the HMAC shared secret.
 */

var KS_BRIDGE_SHARED_SECRET_PROP = 'KS_APPS_SCRIPT_SHARED_SECRET';
var KS_BRIDGE_MAX_SKEW_SECONDS = 300;

/**
 * Compute lowercase hexadecimal HMAC-SHA256 signature using Apps Script Utilities.
 *
 * @param {string} messageUtf8
 * @param {string} secretUtf8
 * @return {string}
 */
function ksComputeHmacSha256Hex_(messageUtf8, secretUtf8) {
  var sigBytes = Utilities.computeHmacSha256Signature(
    Utilities.newBlob(String(messageUtf8 || ''), 'application/json', 'envelope.json').getBytes(),
    Utilities.newBlob(String(secretUtf8 || ''), 'text/plain', 'secret.txt').getBytes()
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
 * Verify mandatory HMAC-SHA256 signature and timestamp skew on incoming Web App request.
 * Fails closed on any missing secret, weak secret (<32 chars), malformed JSON, missing
 * `canonical_envelope`, signature mismatch, or timestamp outside ±300 seconds.
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

  if (
    !outer ||
    typeof outer !== 'object' ||
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
 * Integration pattern inside bound `WebAppBridge.js`:
 *   function doPost(e) {
 *     var auth = ksVerifySignedBridgeEnvelope_(e);
 *     if (!auth.ok) {
 *       return ksJsonOutput_(auth.errorResponse);
 *     }
 *     return ksJsonOutput_(ksRouteGovernedWriteWithBootstrap_(auth.envelope, ksDispatchExistingGovernedAction_));
 *   }
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
