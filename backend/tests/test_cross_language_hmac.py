"""
Kawad Swad ERP — Cross-Language Python <-> Apps Script HMAC-SHA256 Test Suite.

Executes REAL Python signing (`AppsScriptBridge.sign_envelope` + exact canonical JSON
serialization with `separators=(",", ":")`, `sort_keys=True`, `ensure_ascii=True`) and
verifies every generated wire envelope directly inside a Node.js VM running the ACTUAL
bound Apps Script files from `apps_script/`:
  - `apps_script/WebAppBridge_BootstrapIntegration.js`
  - `apps_script/WebAppBridge.js`
  (plus full-stack check with `Config.js`, `SafeWriter.js`, `IdAllocator.js`,
   `AuditAndExceptions.js`, `BootstrapOwnerHandler.js`).

100% offline / read-only against production: never touches Google Sheets, live Apps Script,
or Render.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import unittest
import uuid
from datetime import datetime, timedelta, timezone

BACKEND_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
REPO_ROOT = os.path.abspath(os.path.join(BACKEND_DIR, ".."))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

os.environ.setdefault("SALES_TESTING", "1")
os.environ.setdefault("SALES_ENV", "development")

from app.apps_script_bridge import AppsScriptBridge  # noqa: E402
from app.timeutil import now_iso  # noqa: E402

SHARED_SECRET = "KsCrossLangHmacSharedSecret2026!@#9876543210abcdef"
WRONG_SECRET = "KsWrongHmacSharedSecret2026!@#00000000000000000000"
BOOTSTRAP_SECRET = "KsCrossLangOwnerBootstrapSecret2026!@#112233445566"
BOOTSTRAP_DIGEST = hashlib.sha256(BOOTSTRAP_SECRET.encode("utf-8")).hexdigest()
VALID_PW_HASH = "pbkdf2:sha256:100000$" + ("a" * 32) + "$" + ("b" * 64)


def _python_build_wire_envelope(
    *,
    action: str = "BOOTSTRAP_FIRST_OWNER",
    target_tab: str = "Users",
    nonce: str = "XLANG-NONCE-001",
    correlation_id: str = "CORR-XLANG-001",
    transaction_id: str = "TXN-XLANG-001",
    attempt_number: int = 1,
    payload_hash: str = "d" * 64,
    actor_user_id: str = "BOOTSTRAP_OWNER_INIT",
    actor_role: str = "OWNER_ADMIN",
    timestamp: str | None = None,
    payload: dict | None = None,
    secret: str = SHARED_SECRET,
    contract_version: str = "2.0",
    signature_alg: str = "HMAC-SHA-256",
    outer_overrides: dict | None = None,
    signature_override: str | None = None,
    omit_signature: bool = False,
    omit_canonical: bool = False,
) -> tuple[str, str, str]:
    """Build exact wire_body using the identical canonicalization & HMAC code path as apps_script_bridge.py."""
    envelope = {
        "action": action,
        "target_tab": target_tab,
        "nonce": nonce,
        "correlation_id": correlation_id,
        "transaction_id": transaction_id,
        "attempt_number": attempt_number,
        "payload_hash": payload_hash,
        "actor_user_id": actor_user_id,
        "actor_role": actor_role,
        "timestamp": timestamp if timestamp is not None else now_iso(),
        "payload": payload if payload is not None else {
            "username": "kawad.owner",
            "full_name": "Rajesh Kawad",
            "password_hash": VALID_PW_HASH,
            "role": "OWNER_ADMIN",
            "must_change_password": "false",
            "bootstrap_token_digest": BOOTSTRAP_DIGEST,
        },
    }
    canonical_body = json.dumps(
        envelope,
        separators=(",", ":"),
        sort_keys=True,
        ensure_ascii=True,
        default=str,
    )
    signature = (
        signature_override
        if signature_override is not None
        else AppsScriptBridge.sign_envelope(canonical_body, secret)
    )
    wire_envelope = dict(envelope)
    wire_envelope["contract_version"] = contract_version
    wire_envelope["signature_alg"] = signature_alg
    if not omit_signature:
        wire_envelope["signature"] = signature
    if not omit_canonical:
        wire_envelope["canonical_envelope"] = canonical_body
    if outer_overrides:
        wire_envelope.update(outer_overrides)
    wire_body = json.dumps(
        wire_envelope,
        separators=(",", ":"),
        sort_keys=True,
        ensure_ascii=True,
        default=str,
    )
    return wire_body, canonical_body, signature


_NODE_HARNESS = r"""
const crypto = require('node:crypto');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const input = JSON.parse(fs.readFileSync(0, 'utf8'));
const appsDir = path.resolve(input.appsDir);

const propsStore = new Map(Object.entries(input.scriptProps || {}));
let lockCalls = [];
let legacyCalls = [];

const lockObj = {
  tryLock(ms) { lockCalls.push(['tryLock', ms]); return true; },
  waitLock(ms) { lockCalls.push(['waitLock', ms]); },
  hasLock() { return lockCalls.some(c => c[0] === 'tryLock' || c[0] === 'waitLock'); },
  releaseLock() { lockCalls.push(['releaseLock']); },
};

const sandbox = {
  console, Date, Math, JSON, Object, Array, String, Number, Boolean, RegExp, Error, parseInt, isNaN,
  LockService: { getScriptLock: () => lockObj },
  PropertiesService: {
    getScriptProperties: () => ({
      getProperty: (k) => (propsStore.has(k) ? propsStore.get(k) : null),
      setProperty: (k, v) => propsStore.set(k, String(v)),
      setProperties: (o) => { for (const [k, v] of Object.entries(o)) propsStore.set(k, String(v)); },
      deleteProperty: (k) => propsStore.delete(k),
    }),
  },
  ContentService: {
    MimeType: { JSON: 'application/json' },
    createTextOutput: (str) => ({
      _text: str,
      setMimeType() { return this; },
      getContent() { return this._text; },
    }),
  },
  Utilities: {
    Charset: { UTF_8: 'utf8' },
    getUuid: () => crypto.randomUUID(),
    computeHmacSha256Signature(msg, secret) {
      const buf = crypto.createHmac('sha256', Buffer.from(String(secret), 'utf8'))
        .update(Buffer.from(String(msg), 'utf8'))
        .digest();
      return Array.from(buf).map((b) => (b > 127 ? b - 256 : b));
    },
  },
  SpreadsheetApp: {
    getActiveSpreadsheet: () => null,
    flush: () => {},
  },
};

const ctx = vm.createContext(sandbox);
for (const fname of input.loadFiles) {
  const code = fs.readFileSync(path.join(appsDir, fname), 'utf8');
  vm.runInContext(code, ctx, { filename: fname });
}

if (input.stubLegacyRoute) {
  ctx.ksVerifyBridgeActor_ = (uid, role) => {
    legacyCalls.push(['ksVerifyBridgeActor_', uid, role]);
    return { ok: true, user_id: uid, canonical_role: role };
  };
  ctx.ksFindByNonce_ = (nonce) => { legacyCalls.push(['ksFindByNonce_', nonce]); return null; };
  ctx.ksRouteGovernedWrite_ = (action, tab, payload) => {
    legacyCalls.push(['ksRouteGovernedWrite_', action, tab]);
    return { allocated_id: 'CUST-20261125-00001', record: payload };
  };
  ctx.ksRecordIdAllocation_ = (nonce, tab, id) => { legacyCalls.push(['ksRecordIdAllocation_', nonce, tab, id]); };
  ctx.ksLogAuditStrictLocked_ = (action, tab, id, opts) => {
    legacyCalls.push(['ksLogAuditStrictLocked_', action, tab, id, Boolean(opts && opts.callerHoldsLock)]);
    return { audit_id: 'AUD-20261126-00001', row: 2, record: {} };
  };
}

if (input.stubBootstrapHandler) {
  ctx.ksBootstrapFirstOwner_ = (env) => ({
    status: 'CONFIRMED',
    correlation_id: env.correlation_id,
    nonce: env.nonce,
    action: env.action,
    target_tab: env.target_tab,
    allocated_id: 'USR-20261125-00001',
    record: { user_id: 'USR-20261125-00001', role: 'OWNER_ADMIN' },
  });
}

let result;
if (input.mode === 'verify_only') {
  result = ctx.ksVerifySignedBridgeEnvelope_(input.event);
} else if (input.mode === 'doPost') {
  const out = ctx.doPost(input.event);
  result = JSON.parse(out.getContent());
} else if (input.mode === 'compare_hmac') {
  result = {
    ksComputeHmacSha256Hex_: ctx.ksComputeHmacSha256Hex_(input.message, input.secret),
    ksHmacSha256Hex_: ctx.ksHmacSha256Hex_(input.message, input.secret),
    safeEqualSame: ctx.ksBridgeSafeEqual_(input.expected, input.expected),
    safeEqualDiff: ctx.ksBridgeSafeEqual_(input.expected, '0'.repeat(64)),
    safeEqualEmpty: ctx.ksBridgeSafeEqual_('', ''),
    webAppSafeEqualSame: ctx.ksSafeEqual_(input.expected, input.expected),
    webAppSafeEqualDiff: ctx.ksSafeEqual_(input.expected, '0'.repeat(64)),
    webAppSafeEqualLenDiff: ctx.ksSafeEqual_(input.expected, input.expected.slice(0, 10)),
  };
}

process.stdout.write(JSON.stringify({ result, lockCalls, legacyCalls }));
"""


def _run_apps_script_vm(payload: dict) -> dict:
    proc = subprocess.run(
        ["node", "-e", _NODE_HARNESS],
        input=json.dumps(payload),
        text=True,
        capture_output=True,
        cwd=REPO_ROOT,
        timeout=15,
        check=True,
    )
    return json.loads(proc.stdout)


class TestCrossLanguageHmacAuthentication(unittest.TestCase):
    APPS_DIR = os.path.join(REPO_ROOT, "apps_script")

    def test_01_positive_python_hmac_matches_apps_script_byte_for_byte_ascii_and_unicode(self):
        samples = [
            '{"action":"BOOTSTRAP_FIRST_OWNER","nonce":"N-1","payload":{"full_name":"Rajesh Kawad"}}',
            json.dumps(
                {
                    "action": "BOOTSTRAP_FIRST_OWNER",
                    "payload": {
                        "full_name": "राजेश कावड — ₹12,500.50",
                        "notes": 'Line 1\nLine 2 \\ "quoted" / éàü',
                        "active": True,
                        "count": 0,
                        "empty": None,
                    },
                },
                separators=(",", ":"),
                sort_keys=True,
                ensure_ascii=True,
            ),
            # Raw UTF-8 non-ASCII directly (defense-in-depth UTF-8 charset parity)
            "राजेश कावड ₹500 — UTF-8 direct",
        ]
        for msg in samples:
            py_sig = AppsScriptBridge.sign_envelope(msg, SHARED_SECRET)
            out = _run_apps_script_vm({
                "appsDir": self.APPS_DIR,
                "loadFiles": ["WebAppBridge_BootstrapIntegration.js", "WebAppBridge.js"],
                "mode": "compare_hmac",
                "message": msg,
                "secret": SHARED_SECRET,
                "expected": py_sig,
            })
            res = out["result"]
            self.assertEqual(res["ksComputeHmacSha256Hex_"], py_sig)
            self.assertEqual(res["ksHmacSha256Hex_"], py_sig)
            self.assertTrue(res["safeEqualSame"])
            self.assertFalse(res["safeEqualDiff"])
            self.assertFalse(res["safeEqualEmpty"])
            self.assertTrue(res["webAppSafeEqualSame"])
            self.assertFalse(res["webAppSafeEqualDiff"])
            self.assertFalse(res["webAppSafeEqualLenDiff"])

    def test_02_positive_python_signed_bootstrap_and_unicode_verified_standalone(self):
        # Verify WebAppBridge_BootstrapIntegration.js works WITHOUT BootstrapOwnerHandler.js loaded
        wire_body, _, _ = _python_build_wire_envelope(
            payload={
                "username": "kawad.owner",
                "full_name": "राजेश कावड",
                "notes": "Initial Owner ₹0 — \"verified\"",
                "password_hash": VALID_PW_HASH,
                "role": "OWNER_ADMIN",
                "must_change_password": "false",
                "bootstrap_token_digest": BOOTSTRAP_DIGEST,
            }
        )
        out = _run_apps_script_vm({
            "appsDir": self.APPS_DIR,
            "loadFiles": ["WebAppBridge_BootstrapIntegration.js"],
            "scriptProps": {"SALES_APPS_SCRIPT_SHARED_SECRET": SHARED_SECRET},
            "mode": "verify_only",
            "event": {"postData": {"contents": wire_body}},
        })
        self.assertTrue(out["result"]["ok"])
        self.assertEqual(out["result"]["envelope"]["action"], "BOOTSTRAP_FIRST_OWNER")
        self.assertEqual(out["result"]["envelope"]["payload"]["full_name"], "राजेश कावड")

    def test_03_positive_z_and_ist_offset_timestamps_accepted(self):
        utc_z = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        ist_offset = (datetime.now(timezone.utc) + timedelta(hours=5, minutes=30)).strftime(
            "%Y-%m-%dT%H:%M:%S+05:30"
        )
        for ts in (utc_z, ist_offset, now_iso()):
            wire_body, _, _ = _python_build_wire_envelope(timestamp=ts)
            out = _run_apps_script_vm({
                "appsDir": self.APPS_DIR,
                "loadFiles": ["WebAppBridge_BootstrapIntegration.js"],
                "scriptProps": {"SALES_APPS_SCRIPT_SHARED_SECRET": SHARED_SECRET},
                "mode": "verify_only",
                "event": {"postData": {"contents": wire_body}},
            })
            self.assertTrue(out["result"]["ok"], f"Timestamp {ts} should be accepted: {out}")

    def test_04_positive_bootstrap_isolated_from_legacy_nonce_flow_in_dopost(self):
        wire_body, _, _ = _python_build_wire_envelope(action="BOOTSTRAP_FIRST_OWNER", target_tab="Users")
        out = _run_apps_script_vm({
            "appsDir": self.APPS_DIR,
            "loadFiles": ["WebAppBridge_BootstrapIntegration.js", "WebAppBridge.js"],
            "scriptProps": {"SALES_APPS_SCRIPT_SHARED_SECRET": SHARED_SECRET},
            "mode": "doPost",
            "stubLegacyRoute": True,
            "stubBootstrapHandler": True,
            "event": {"postData": {"contents": wire_body}},
        })
        self.assertEqual(out["result"]["status"], "CONFIRMED")
        self.assertEqual(out["result"]["allocated_id"], "USR-20261125-00001")
        # Must NEVER touch WebAppBridge.js legacy lock, ksFindByNonce_, ksRouteGovernedWrite_, or ksRecordIdAllocation_
        self.assertEqual(out["lockCalls"], [])
        self.assertEqual(out["legacyCalls"], [])

    def test_05_positive_non_bootstrap_governed_action_authenticates_then_routes_legacy(self):
        wire_body, _, _ = _python_build_wire_envelope(
            action="CREATE_CUSTOMER",
            target_tab="Customers",
            payload={"customer_name": "Sharma Kirana"},
        )
        out = _run_apps_script_vm({
            "appsDir": self.APPS_DIR,
            "loadFiles": ["WebAppBridge_BootstrapIntegration.js", "WebAppBridge.js"],
            "scriptProps": {"SALES_APPS_SCRIPT_SHARED_SECRET": SHARED_SECRET},
            "mode": "doPost",
            "stubLegacyRoute": True,
            "event": {"postData": {"contents": wire_body}},
        })
        self.assertEqual(out["result"]["status"], "CONFIRMED")
        self.assertEqual(out["result"]["action"], "CREATE_CUSTOMER")
        self.assertTrue(any(c[0] == "ksRouteGovernedWrite_" for c in out["legacyCalls"]))

    def test_06_negative_missing_invalid_wrong_secret_and_malformed_signatures_rejected_before_dispatch(self):
        _, _, valid_sig = _python_build_wire_envelope()
        flipped_sig = ("0" if valid_sig[0] != "0" else "1") + valid_sig[1:]

        cases = [
            ("missing_signature", _python_build_wire_envelope(omit_signature=True)[0], "MISSING_OR_MALFORMED_HMAC_ENVELOPE", 401),
            ("empty_signature", _python_build_wire_envelope(signature_override="")[0], "MISSING_OR_MALFORMED_HMAC_ENVELOPE", 401),
            ("short_signature", _python_build_wire_envelope(signature_override="abcdef")[0], "MISSING_OR_MALFORMED_HMAC_ENVELOPE", 401),
            ("non_hex_signature", _python_build_wire_envelope(signature_override="z" * 64)[0], "MISSING_OR_MALFORMED_HMAC_ENVELOPE", 401),
            ("missing_canonical", _python_build_wire_envelope(omit_canonical=True)[0], "MISSING_OR_MALFORMED_HMAC_ENVELOPE", 401),
            ("bit_flipped_signature", _python_build_wire_envelope(signature_override=flipped_sig)[0], "INVALID_SIGNATURE", 401),
            ("wrong_secret", _python_build_wire_envelope(secret=WRONG_SECRET)[0], "INVALID_SIGNATURE", 401),
            ("wrong_contract_version", _python_build_wire_envelope(contract_version="1.0")[0], "UNSUPPORTED_CONTRACT_VERSION", 400),
            ("missing_contract_version", _python_build_wire_envelope(contract_version="")[0], "UNSUPPORTED_CONTRACT_VERSION", 400),
            ("wrong_signature_alg", _python_build_wire_envelope(signature_alg="HMAC-SHA-512")[0], "UNSUPPORTED_SIGNATURE_ALG", 400),
            ("none_signature_alg", _python_build_wire_envelope(signature_alg="none")[0], "UNSUPPORTED_SIGNATURE_ALG", 400),
        ]
        for label, wire_body, expected_code, expected_http in cases:
            out = _run_apps_script_vm({
                "appsDir": self.APPS_DIR,
                "loadFiles": ["WebAppBridge_BootstrapIntegration.js", "WebAppBridge.js"],
                "scriptProps": {"SALES_APPS_SCRIPT_SHARED_SECRET": SHARED_SECRET},
                "mode": "doPost",
                "stubLegacyRoute": True,
                "stubBootstrapHandler": True,
                "event": {"postData": {"contents": wire_body}},
            })
            self.assertEqual(out["result"]["status"], "REJECTED", f"Case {label} failed: {out}")
            self.assertEqual(out["result"]["error_code"], expected_code, f"Case {label} code mismatch: {out}")
            self.assertEqual(out["result"]["http_status"], expected_http, f"Case {label} http mismatch: {out}")
            # Authentication MUST reject before ScriptLock or any action dispatch
            self.assertEqual(out["lockCalls"], [], f"Case {label} should not acquire lock")
            self.assertEqual(out["legacyCalls"], [], f"Case {label} should not dispatch")

    def test_07_negative_expired_future_and_malformed_timestamps_rejected(self):
        past_ts = (datetime.now(timezone.utc) - timedelta(seconds=310)).isoformat()
        future_ts = (datetime.now(timezone.utc) + timedelta(seconds=310)).isoformat()
        cases = [
            ("expired_past", past_ts, "ENVELOPE_TIMESTAMP_SKEW_EXCEEDED"),
            ("expired_future", future_ts, "ENVELOPE_TIMESTAMP_SKEW_EXCEEDED"),
            ("missing_tz", "2026-11-25T10:00:00", "INVALID_ENVELOPE_TIMESTAMP"),
            ("date_only", "2026-11-25", "INVALID_ENVELOPE_TIMESTAMP"),
            ("garbage", "not-a-timestamp", "INVALID_ENVELOPE_TIMESTAMP"),
            ("empty", "", "INVALID_ENVELOPE_TIMESTAMP"),
        ]
        for label, ts, expected_code in cases:
            wire_body, _, _ = _python_build_wire_envelope(timestamp=ts)
            out = _run_apps_script_vm({
                "appsDir": self.APPS_DIR,
                "loadFiles": ["WebAppBridge_BootstrapIntegration.js", "WebAppBridge.js"],
                "scriptProps": {"SALES_APPS_SCRIPT_SHARED_SECRET": SHARED_SECRET},
                "mode": "doPost",
                "event": {"postData": {"contents": wire_body}},
            })
            self.assertEqual(out["result"]["status"], "REJECTED", f"Timestamp case {label}: {out}")
            self.assertEqual(out["result"]["error_code"], expected_code, f"Timestamp case {label}: {out}")
            self.assertEqual(out["result"]["http_status"], 401)

    def test_08_negative_outer_field_tampering_and_malformed_json_structures_rejected(self):
        for field, bad_val in (
            ("action", "DELETE_EVERYTHING"),
            ("target_tab", "AuditLog"),
            ("nonce", "TAMPERED-NONCE"),
            ("payload_hash", "0" * 64),
            ("actor_role", "SUPER_ADMIN"),
            ("timestamp", "2099-01-01T00:00:00Z"),
        ):
            wire_body, _, _ = _python_build_wire_envelope(outer_overrides={field: bad_val})
            out = _run_apps_script_vm({
                "appsDir": self.APPS_DIR,
                "loadFiles": ["WebAppBridge_BootstrapIntegration.js", "WebAppBridge.js"],
                "scriptProps": {"SALES_APPS_SCRIPT_SHARED_SECRET": SHARED_SECRET},
                "mode": "doPost",
                "event": {"postData": {"contents": wire_body}},
            })
            self.assertEqual(out["result"]["status"], "REJECTED", f"Outer tamper {field}: {out}")
            self.assertEqual(out["result"]["error_code"], "OUTER_ENVELOPE_TAMPER_DETECTED")
            self.assertEqual(out["result"]["http_status"], 401)

        # Array outer JSON body rejected
        out_arr = _run_apps_script_vm({
            "appsDir": self.APPS_DIR,
            "loadFiles": ["WebAppBridge_BootstrapIntegration.js", "WebAppBridge.js"],
            "scriptProps": {"SALES_APPS_SCRIPT_SHARED_SECRET": SHARED_SECRET},
            "mode": "doPost",
            "event": {"postData": {"contents": "[]"}},
        })
        self.assertEqual(out_arr["result"]["error_code"], "INVALID_JSON_BODY")

        # Signed canonical_envelope that decodes to a JSON array rejected
        arr_canonical = "[1,2,3]"
        arr_sig = AppsScriptBridge.sign_envelope(arr_canonical, SHARED_SECRET)
        arr_wire = json.dumps({
            "contract_version": "2.0",
            "signature_alg": "HMAC-SHA-256",
            "canonical_envelope": arr_canonical,
            "signature": arr_sig,
        })
        out_env_arr = _run_apps_script_vm({
            "appsDir": self.APPS_DIR,
            "loadFiles": ["WebAppBridge_BootstrapIntegration.js", "WebAppBridge.js"],
            "scriptProps": {"SALES_APPS_SCRIPT_SHARED_SECRET": SHARED_SECRET},
            "mode": "doPost",
            "event": {"postData": {"contents": arr_wire}},
        })
        self.assertEqual(out_env_arr["result"]["error_code"], "INVALID_CANONICAL_ENVELOPE")

        # Signed envelope with non-object payload rejected
        wire_bad_payload, _, _ = _python_build_wire_envelope(payload="not-an-object")  # type: ignore[arg-type]
        out_bad_payload = _run_apps_script_vm({
            "appsDir": self.APPS_DIR,
            "loadFiles": ["WebAppBridge_BootstrapIntegration.js", "WebAppBridge.js"],
            "scriptProps": {"SALES_APPS_SCRIPT_SHARED_SECRET": SHARED_SECRET},
            "mode": "doPost",
            "event": {"postData": {"contents": wire_bad_payload}},
        })
        self.assertEqual(out_bad_payload["result"]["error_code"], "INVALID_ENVELOPE_PAYLOAD")

    def test_09_negative_missing_verifier_and_weak_secret_fail_closed(self):
        wire_body, _, _ = _python_build_wire_envelope()
        # WebAppBridge.js alone without WebAppBridge_BootstrapIntegration.js MUST fail closed (503)
        out_missing = _run_apps_script_vm({
            "appsDir": self.APPS_DIR,
            "loadFiles": ["WebAppBridge.js"],
            "scriptProps": {"SALES_APPS_SCRIPT_SHARED_SECRET": SHARED_SECRET},
            "mode": "doPost",
            "event": {"postData": {"contents": wire_body}},
        })
        self.assertEqual(out_missing["result"]["status"], "REJECTED")
        self.assertEqual(out_missing["result"]["error_code"], "BRIDGE_AUTH_VERIFIER_MISSING")
        self.assertEqual(out_missing["result"]["http_status"], 503)

        # Weak shared secret (< 32 chars) MUST fail closed (503)
        out_weak = _run_apps_script_vm({
            "appsDir": self.APPS_DIR,
            "loadFiles": ["WebAppBridge_BootstrapIntegration.js", "WebAppBridge.js"],
            "scriptProps": {"SALES_APPS_SCRIPT_SHARED_SECRET": "too-short-secret"},
            "mode": "doPost",
            "event": {"postData": {"contents": wire_body}},
        })
        self.assertEqual(out_weak["result"]["status"], "REJECTED")
        self.assertEqual(out_weak["result"]["error_code"], "BRIDGE_NOT_CONFIGURED")
        self.assertEqual(out_weak["result"]["http_status"], 503)

    def _run_real_sheet_bridge_scenario(
        self,
        requests_list,
        *,
        initial_sheets=None,
        corrupt_readback_tab=None,
        corrupt_readback_col=0,
        fail_audit_tab=False,
    ):
        """Runs real Apps Script modules (Config, SafeWriter, IdAllocator, AuditAndExceptions, WebAppBridge_BootstrapIntegration, WebAppBridge) against an in-memory Google Sheets workbook."""
        script = r"""
const fs = require('fs');
const path = require('path');
const vm = require('vm');
const crypto = require('crypto');

const input = JSON.parse(fs.readFileSync(0, 'utf8'));
const sheetsData = {};
for (const [name, rows] of Object.entries(input.initialSheets)) {
  sheetsData[name] = rows.map(r => r.slice());
}

function makeSheet(name) {
  return {
    getName() { return name; },
    getLastRow() { return sheetsData[name].length; },
    getLastColumn() { return sheetsData[name].length ? sheetsData[name][0].length : 0; },
    getDataRange() {
      const rows = sheetsData[name];
      return { getValues() { return rows.map(r => r.slice()); } };
    },
    getRange(row, col, numRows, numCols) {
      const r0 = row - 1, c0 = col - 1;
      return {
        getValues() {
          const out = [];
          for (let r = 0; r < numRows; r++) {
            const src = sheetsData[name][r0 + r] || [];
            const line = [];
            for (let c = 0; c < numCols; c++) {
              let v = c0 + c < src.length ? src[c0 + c] : '';
              if (input.corruptReadbackTab === name && r0 + r >= 1 && c0 + c === input.corruptReadbackCol) {
                v = 'CORRUPTED-VALUE';
              }
              line.push(v);
            }
            out.push(line);
          }
          return out;
        },
        setValues(vals) {
          if (input.failAuditTab && name === 'AuditLog') {
            throw new Error('SIMULATED_AUDIT_SHEET_WRITE_FAILURE');
          }
          for (let r = 0; r < vals.length; r++) {
            while (sheetsData[name].length <= r0 + r) sheetsData[name].push([]);
            for (let c = 0; c < vals[r].length; c++) {
              sheetsData[name][r0 + r][c0 + c] = vals[r][c];
            }
          }
        }
      };
    },
    appendRow(row) {
      if (input.failAuditTab && name === 'AuditLog') {
        throw new Error('SIMULATED_AUDIT_SHEET_WRITE_FAILURE');
      }
      sheetsData[name].push(row.slice());
    }
  };
}

let locked = false;
const lockEvents = [];
let flushCount = 0;

const sandbox = {
  console,
  Date,
  Math,
  JSON,
  Object,
  Array,
  String,
  Number,
  Boolean,
  RegExp,
  Error,
  parseInt,
  isNaN,
  PropertiesService: {
    getScriptProperties() {
      return { getProperty(k) { return input.scriptProps[k] ?? null; } };
    }
  },
  LockService: {
    getScriptLock() {
      return {
        waitLock(ms) { lockEvents.push(['waitLock', ms]); locked = true; },
        hasLock() { return locked; },
        releaseLock() { lockEvents.push(['releaseLock']); locked = false; },
      };
    }
  },
  SpreadsheetApp: {
    getActiveSpreadsheet() {
      return {
        getSheetByName(n) { return Object.prototype.hasOwnProperty.call(sheetsData, n) ? makeSheet(n) : null; }
      };
    },
    flush() { lockEvents.push(['flush', locked]); flushCount++; }
  },
  Utilities: {
    Charset: { UTF_8: 'UTF-8' },
    computeHmacSha256Signature(msg, secret) {
      const buf = crypto.createHmac('sha256', Buffer.from(String(secret), 'utf8')).update(Buffer.from(String(msg), 'utf8')).digest();
      return Array.from(buf, b => (b > 127 ? b - 256 : b));
    },
    formatDate(d, tz, fmt) {
      if (fmt === 'yyyyMMdd') return '20261126';
      return new Date(d).toISOString();
    },
    getUuid() { return 'uuid-fixed-001'; }
  },
  ContentService: {
    MimeType: { JSON: 'application/json' },
    createTextOutput(text) { return { getContent() { return text; }, setMimeType() { return this; } }; }
  },
  Session: { getActiveUser() { return { getEmail() { return 'owner@kawadswad.test'; } }; } },
};

const ctx = vm.createContext(sandbox);
for (const fname of ['Config.js', 'SafeWriter.js', 'IdAllocator.js', 'AuditAndExceptions.js', 'WebAppBridge_BootstrapIntegration.js', 'WebAppBridge.js']) {
  vm.runInContext(fs.readFileSync(path.join(input.appsDir, fname), 'utf8'), ctx, { filename: fname });
}

const responses = [];
for (const wireBody of input.requests) {
  const out = ctx.doPost({ postData: { contents: wireBody } });
  responses.push(JSON.parse(out.getContent()));
}
process.stdout.write(JSON.stringify({ responses, sheetsData, lockEvents, flushCount, locked }));
"""
        sheets = initial_sheets if initial_sheets is not None else {
            "Users": [
                ["user_id", "full_name", "username", "role", "active"],
                ["USR-20261126-00001", "Rajesh Kawad", "kawad.owner", "OWNER_ADMIN", True],
                ["USR-1", "Owner Test", "owner1", "OWNER_ADMIN", True],
                ["USR-SALES-1", "Ramesh Salesman", "ramesh.s", "FIELD_SALESMAN", True],
                ["USR-AUD-1", "CA Auditor", "ca.auditor", "AUDITOR", True],
                ["USR-INACTIVE-1", "Former Staff", "old.staff", "FIELD_SALESMAN", False],
            ],
            "IdAllocations": [
                ["allocation_id", "tab_name", "allocated_id", "nonce", "created_at"],
                # Legacy 13-digit epoch timestamp row to verify W6 does NOT jump sequence
                ["ALLOC-1764000000000", "Customers", "CUST-OLD-00001", "LEGACY-EPOCH-NONCE", "2026-11-20T00:00:00Z"],
            ],
            "AuditLog": [[
                "audit_id", "event_datetime", "actor_user_id", "action", "entity_type",
                "entity_id", "field_changed", "old_value", "new_value", "reason",
                "approved_by_user_id", "related_record_id"
            ]],
            "ExceptionRegister": [[
                "exception_id", "created_at", "severity", "source_function", "tab_name",
                "reference_id", "error_message", "payload_json", "assigned_owner",
                "due_date", "status", "resolution_notes", "resolved_by", "resolved_at"
            ]],
            "Customers": [[
                "customer_id", "customer_type", "shop_name", "shopkeeper_name", "mobile",
                "alternate_mobile", "address", "locality_area", "city", "map_location",
                "active", "created_at", "notes", "gstin", "nonce"
            ]],
            "AuthUsers": [["auth_id", "user_id", "username", "password_hash", "must_change_password", "nonce"]],
            "Settings": [["setting_key", "setting_value", "nonce"]],
            "Products": [["product_id", "sku", "product_name", "active", "nonce"]],
        }
        proc = subprocess.run(
            ["node", "-e", script],
            input=json.dumps({
                "appsDir": self.APPS_DIR,
                "scriptProps": {"SALES_APPS_SCRIPT_SHARED_SECRET": SHARED_SECRET},
                "initialSheets": sheets,
                "requests": requests_list,
                "corruptReadbackTab": corrupt_readback_tab,
                "corruptReadbackCol": corrupt_readback_col,
                "failAuditTab": fail_audit_tab,
            }),
            text=True,
            capture_output=True,
            cwd=REPO_ROOT,
            timeout=15,
            check=True,
        )
        return json.loads(proc.stdout)

    def test_10_stage1_real_sheet_bridge_lock_ownership_monotonic_alloc_strict_audit_and_replay(self):
        wire1, _, _ = _python_build_wire_envelope(
            action="CREATE_CUSTOMER",
            target_tab="Customers",
            nonce="KS-CUST-STAGE1-001",
            actor_user_id="USR-20261126-00001",
            actor_role="OWNER_ADMIN",
            payload={"customer_id": "CUST-20261126-00001", "shop_name": "Kawad Mart", "active": True},
        )
        # Replay exact same nonce + tab -> must return CONFIRMED idempotent_replay=True without duplicate rows
        out = self._run_real_sheet_bridge_scenario([wire1, wire1])
        r1, r2 = out["responses"]
        self.assertEqual(r1["status"], "CONFIRMED")
        self.assertEqual(r1["allocated_id"], "CUST-20261126-00001")
        self.assertEqual(r1["record"]["shop_name"], "Kawad Mart")
        self.assertEqual(r2["status"], "CONFIRMED")
        self.assertTrue(r2["idempotent_replay"])
        self.assertEqual(r2["allocated_id"], "CUST-20261126-00001")
        # Exactly 1 new customer row + 1 header
        self.assertEqual(len(out["sheetsData"]["Customers"]), 2)
        # W6: Monotonic ALLOC-0000001 (ignoring legacy 13-digit epoch timestamp) + ALLOC-0000002 for AuditLog
        alloc_ids = [row[0] for row in out["sheetsData"]["IdAllocations"][2:]]
        self.assertEqual(alloc_ids, ["ALLOC-0000001", "ALLOC-0000002"])
        # W1: Strict AuditLog written with canonical AUD-* ID and actor_user_id
        self.assertEqual(len(out["sheetsData"]["AuditLog"]), 2)
        self.assertTrue(out["sheetsData"]["AuditLog"][1][0].startswith("AUD-"))
        self.assertEqual(out["sheetsData"]["AuditLog"][1][2], "USR-20261126-00001")
        # W1: Every flush during the first write occurred while ScriptLock was HELD (locked=True)
        flushes = [ev for ev in out["lockEvents"] if ev[0] == "flush"]
        self.assertGreaterEqual(len(flushes), 4)
        self.assertTrue(all(ev[1] is True for ev in flushes), f"Lock released prematurely before flush: {out['lockEvents']}")
        self.assertFalse(out["locked"])

    def test_11_stage1_w1_mandatory_audit_missing_and_post_write_audit_failure_quarantine(self):
        # 11a: Missing audit logger fails closed BEFORE lock/write
        wire_ok, _, _ = _python_build_wire_envelope(
            action="CREATE_CUSTOMER",
            target_tab="Customers",
            nonce="KS-NO-AUDIT-001",
            actor_user_id="USR-1",
            actor_role="OWNER_ADMIN",
            payload={"customer_id": "CUST-1"},
        )
        out_missing = _run_apps_script_vm({
            "appsDir": self.APPS_DIR,
            "loadFiles": ["WebAppBridge_BootstrapIntegration.js", "WebAppBridge.js"],
            "scriptProps": {"SALES_APPS_SCRIPT_SHARED_SECRET": SHARED_SECRET},
            "mode": "doPost",
            "event": {"postData": {"contents": wire_ok}},
        })
        self.assertEqual(out_missing["result"]["status"], "REJECTED")
        self.assertEqual(out_missing["result"]["error_code"], "MANDATORY_AUDIT_LOGGER_MISSING")
        self.assertEqual(out_missing["result"]["http_status"], 503)
        self.assertEqual(out_missing["lockCalls"], [])

        # 11b: AuditLog failure AFTER business row write MUST quarantine as RECOVERY_REQUIRED (never CONFIRMED/REJECTED)
        out_audit_fail = self._run_real_sheet_bridge_scenario([wire_ok], fail_audit_tab=True)
        res = out_audit_fail["responses"][0]
        self.assertEqual(res["status"], "RECOVERY_REQUIRED")
        self.assertEqual(res["error_code"], "BRIDGE_POST_WRITE_FAILURE")
        self.assertEqual(res["http_status"], 409)
        self.assertFalse(res["retryable"])
        self.assertFalse(out_audit_fail["locked"])

    def test_12_stage1_w2_cross_table_nonce_collision_rejected(self):
        wire_cust, _, _ = _python_build_wire_envelope(
            action="CREATE_CUSTOMER",
            target_tab="Customers",
            nonce="KS-COLLISION-NONCE-01",
            actor_user_id="USR-1",
            actor_role="OWNER_ADMIN",
            payload={"customer_id": "CUST-20261126-00010", "shop_name": "Alpha"},
        )
        wire_prod, _, _ = _python_build_wire_envelope(
            action="CREATE_PRODUCT",
            target_tab="Products",
            nonce="KS-COLLISION-NONCE-01",
            actor_user_id="USR-1",
            actor_role="OWNER_ADMIN",
            payload={"product_id": "PRD-20261126-00010", "sku": "SKU-1"},
        )
        out = self._run_real_sheet_bridge_scenario([wire_cust, wire_prod])
        self.assertEqual(out["responses"][0]["status"], "CONFIRMED")
        self.assertEqual(out["responses"][1]["status"], "REJECTED")
        self.assertEqual(out["responses"][1]["error_code"], "NONCE_TARGET_TAB_CONFLICT")
        self.assertEqual(out["responses"][1]["http_status"], 409)

    def test_13_stage1_w3_w4_target_tab_allowlist_governance_scratch_authusers_and_actor_checks(self):
        cases = [
            ("AuditLog", "CREATE_CUSTOMER", "USR-1", "OWNER_ADMIN", "GOVERNANCE_TAB_WRITE_FORBIDDEN", 403),
            ("IdAllocations", "CREATE_CUSTOMER", "USR-1", "OWNER_ADMIN", "GOVERNANCE_TAB_WRITE_FORBIDDEN", 403),
            ("ExceptionRegister", "CREATE_CUSTOMER", "USR-1", "OWNER_ADMIN", "GOVERNANCE_TAB_WRITE_FORBIDDEN", 403),
            ("KS_P1_ScratchTab", "CREATE_CUSTOMER", "USR-1", "OWNER_ADMIN", "SCRATCH_TAB_FORBIDDEN", 403),
            ("DBV5_LegacyTemp", "CREATE_CUSTOMER", "USR-1", "OWNER_ADMIN", "SCRATCH_TAB_FORBIDDEN", 403),
            ("AuthUsers", "UPDATE_CUSTOMER", "USR-1", "OWNER_ADMIN", "AUTH_USERS_ACTION_FORBIDDEN", 403),
            ("ArbitraryRogueSheet", "CREATE_CUSTOMER", "USR-1", "OWNER_ADMIN", "UNAPPROVED_TARGET_TAB", 403),
            ("Customers", "CREATE_CUSTOMER", "", "OWNER_ADMIN", "MISSING_ACTOR_IDENTITY", 401),
            ("Customers", "CREATE_CUSTOMER", "USR-1", "", "MISSING_ACTOR_IDENTITY", 401),
        ]
        reqs = [
            _python_build_wire_envelope(
                action=act,
                target_tab=tab,
                nonce=f"KS-GUARD-{idx}",
                actor_user_id=uid,
                actor_role=role,
                payload={"x": 1},
            )[0]
            for idx, (tab, act, uid, role, _, _) in enumerate(cases)
        ]
        # Also verify authorized CHANGE_PASSWORD on AuthUsers IS permitted
        reqs.append(
            _python_build_wire_envelope(
                action="CHANGE_PASSWORD",
                target_tab="AuthUsers",
                nonce="KS-AUTH-OK-01",
                actor_user_id="USR-1",
                actor_role="OWNER_ADMIN",
                payload={"auth_id": "AUTH-20261126-00001", "user_id": "USR-1", "must_change_password": False},
            )[0]
        )
        out = self._run_real_sheet_bridge_scenario(reqs)
        for idx, (tab, act, uid, role, expected_code, expected_http) in enumerate(cases):
            r = out["responses"][idx]
            self.assertEqual(r["status"], "REJECTED", f"Case {tab}/{act} failed: {r}")
            self.assertEqual(r["error_code"], expected_code, f"Case {tab}/{act} failed: {r}")
            self.assertEqual(r["http_status"], expected_http, f"Case {tab}/{act} failed: {r}")
        # Authorized CHANGE_PASSWORD on AuthUsers succeeds
        self.assertEqual(out["responses"][-1]["status"], "CONFIRMED")
        self.assertEqual(len(out["sheetsData"]["AuthUsers"]), 2)

    def test_14_stage1_w5_readback_verification_mismatch_quarantines(self):
        wire_cust, _, _ = _python_build_wire_envelope(
            action="CREATE_CUSTOMER",
            target_tab="Customers",
            nonce="KS-READBACK-FAIL-01",
            actor_user_id="USR-1",
            actor_role="OWNER_ADMIN",
            payload={"customer_id": "CUST-20261126-00099", "shop_name": "Verify Test"},
        )
        out = self._run_real_sheet_bridge_scenario([wire_cust], corrupt_readback_tab="Customers")
        res = out["responses"][0]
        self.assertEqual(res["status"], "RECOVERY_REQUIRED")
        self.assertEqual(res["error_code"], "BRIDGE_POST_WRITE_FAILURE")
        self.assertIn("READBACK_VERIFICATION_FAILED", res["message"])
        # W1/W5: Must record an attributable forensic exception entry in ExceptionRegister
        self.assertEqual(len(out["sheetsData"]["ExceptionRegister"]), 2)
        exc_row = out["sheetsData"]["ExceptionRegister"][1]
        self.assertTrue(exc_row[0].startswith("EXC-"))
        self.assertEqual(exc_row[2], "CRITICAL")
        self.assertIn("READBACK_VERIFICATION_FAILED", exc_row[6])
        self.assertIn("USR-1", exc_row[7])
        self.assertTrue(res.get("recovery_exception_id", "").startswith("EXC-"))

    def test_15_stage5_w4_authoritative_actor_verification_rejects_forged_inactive_escalated_and_uninitialized(self):
        cases = [
            ("forged_user", "USR-FORGED-999", "OWNER_ADMIN", "ACTOR_NOT_FOUND", 403),
            ("inactive_user", "USR-INACTIVE-1", "FIELD_SALESMAN", "ACTOR_INACTIVE", 403),
            ("role_escalation", "USR-SALES-1", "OWNER_ADMIN", "ACTOR_ROLE_MISMATCH", 403),
            ("auditor_claimed", "USR-AUD-1", "AUDITOR", "AUDITOR_WRITE_FORBIDDEN", 403),
            ("auditor_spoofing_owner", "USR-AUD-1", "OWNER_ADMIN", "AUDITOR_WRITE_FORBIDDEN", 403),
        ]
        reqs = [
            _python_build_wire_envelope(
                action="CREATE_CUSTOMER",
                target_tab="Customers",
                nonce=f"KS-W4-{idx}",
                actor_user_id=uid,
                actor_role=role,
                payload={"customer_id": f"CUST-W4-{idx}", "shop_name": "Test Shop"},
            )[0]
            for idx, (_, uid, role, _, _) in enumerate(cases)
        ]
        out = self._run_real_sheet_bridge_scenario(reqs)
        for idx, (label, _, _, expected_code, expected_http) in enumerate(cases):
            r = out["responses"][idx]
            self.assertEqual(r["status"], "REJECTED", f"W4 case {label}: {r}")
            self.assertEqual(r["error_code"], expected_code, f"W4 case {label}: {r}")
            self.assertEqual(r["http_status"], expected_http, f"W4 case {label}: {r}")
        # Zero customer rows written
        self.assertEqual(len(out["sheetsData"]["Customers"]), 1)

        # Uninitialized empty Users directory must fail closed for non-bootstrap writes
        empty_users_sheets = {
            "Users": [["user_id", "full_name", "username", "role", "active"]],
            "IdAllocations": [["allocation_id", "tab_name", "allocated_id", "nonce", "created_at"]],
            "AuditLog": [[
                "audit_id", "event_datetime", "actor_user_id", "action", "entity_type",
                "entity_id", "field_changed", "old_value", "new_value", "reason",
                "approved_by_user_id", "related_record_id"
            ]],
            "Customers": [["customer_id", "shop_name", "nonce"]],
        }
        wire_uninit, _, _ = _python_build_wire_envelope(
            action="CREATE_CUSTOMER",
            target_tab="Customers",
            nonce="KS-W4-UNINIT-1",
            actor_user_id="USR-1",
            actor_role="OWNER_ADMIN",
            payload={"customer_id": "CUST-UNINIT-1", "shop_name": "Blocked"},
        )
        out_uninit = self._run_real_sheet_bridge_scenario([wire_uninit], initial_sheets=empty_users_sheets)
        self.assertEqual(out_uninit["responses"][0]["status"], "REJECTED")
        self.assertEqual(out_uninit["responses"][0]["error_code"], "ACTOR_DIRECTORY_UNINITIALIZED")
        self.assertEqual(out_uninit["responses"][0]["http_status"], 403)

    def test_16_stage5_w3_control_table_systemconfig_action_tab_binding_and_role_restrictions(self):
        cases = [
            # SystemConfig removed from generic writer allowlist -> CONTROL_TABLE_WRITE_FORBIDDEN
            ("SystemConfig", "UPDATE_CA_POLICY", "USR-1", "OWNER_ADMIN", {}, "CONTROL_TABLE_WRITE_FORBIDDEN", 403),
            ("BackupRegister", "UPDATE_CA_POLICY", "USR-1", "OWNER_ADMIN", {}, "CONTROL_TABLE_WRITE_FORBIDDEN", 403),
            ("START_HERE", "UPDATE_CA_POLICY", "USR-1", "OWNER_ADMIN", {}, "CONTROL_TABLE_WRITE_FORBIDDEN", 403),
            # Unregistered action rejected fail-closed
            ("Customers", "ROGUE_UNREGISTERED_ACTION", "USR-1", "OWNER_ADMIN", {}, "UNREGISTERED_BRIDGE_ACTION", 403),
            # Action bound to Products cannot target Customers (prevents routing mismatch)
            ("Customers", "CREATE_PRODUCT", "USR-1", "OWNER_ADMIN", {}, "ACTION_TARGET_TAB_MISMATCH", 403),
            # Non-owner cannot mutate Settings
            ("Settings", "UPDATE_CA_POLICY", "USR-SALES-1", "FIELD_SALESMAN", {"setting_key": "k", "setting_value": "v"}, "INSUFFICIENT_ROLE_FOR_TARGET_TAB", 403),
            # Non-owner cannot change another user's password
            ("AuthUsers", "CHANGE_PASSWORD", "USR-SALES-1", "FIELD_SALESMAN", {"user_id": "USR-1"}, "INSUFFICIENT_ROLE_FOR_AUTH_USERS", 403),
            # Non-owner cannot update another user's profile
            ("Users", "UPDATE_SELF_PROFILE", "USR-SALES-1", "FIELD_SALESMAN", {"user_id": "USR-1"}, "SELF_PROFILE_TARGET_MISMATCH", 403),
        ]
        reqs = [
            _python_build_wire_envelope(
                action=act,
                target_tab=tab,
                nonce=f"KS-W3-{idx}",
                actor_user_id=uid,
                actor_role=role,
                payload=pl,
            )[0]
            for idx, (tab, act, uid, role, pl, _, _) in enumerate(cases)
        ]
        out = self._run_real_sheet_bridge_scenario(reqs)
        for idx, (tab, act, _, _, _, expected_code, expected_http) in enumerate(cases):
            r = out["responses"][idx]
            self.assertEqual(r["status"], "REJECTED", f"W3 case {tab}/{act}: {r}")
            self.assertEqual(r["error_code"], expected_code, f"W3 case {tab}/{act}: {r}")
            self.assertEqual(r["http_status"], expected_http, f"W3 case {tab}/{act}: {r}")

    def test_17_stage5_w2_nonce_action_actor_and_payload_hash_conflict_rejection(self):
        hash_a = "a" * 64
        hash_b = "b" * 64
        wire_orig, _, _ = _python_build_wire_envelope(
            action="CREATE_CUSTOMER",
            target_tab="Customers",
            nonce="KS-W2-BIND-001",
            actor_user_id="USR-1",
            actor_role="OWNER_ADMIN",
            payload_hash=hash_a,
            payload={"customer_id": "CUST-W2-001", "shop_name": "Original Shop"},
        )
        # Same nonce + same tab, DIFFERENT action (UPDATE_CUSTOMER vs CREATE_CUSTOMER)
        wire_diff_action, _, _ = _python_build_wire_envelope(
            action="UPDATE_CUSTOMER",
            target_tab="Customers",
            nonce="KS-W2-BIND-001",
            actor_user_id="USR-1",
            actor_role="OWNER_ADMIN",
            payload_hash=hash_a,
            payload={"customer_id": "CUST-W2-001", "shop_name": "Original Shop"},
        )
        # Same nonce + same tab + same action, DIFFERENT actor
        wire_diff_actor, _, _ = _python_build_wire_envelope(
            action="CREATE_CUSTOMER",
            target_tab="Customers",
            nonce="KS-W2-BIND-001",
            actor_user_id="USR-SALES-1",
            actor_role="FIELD_SALESMAN",
            payload_hash=hash_a,
            payload={"customer_id": "CUST-W2-001", "shop_name": "Original Shop"},
        )
        # Same nonce + same tab + same action + same actor, DIFFERENT payload_hash
        wire_diff_hash, _, _ = _python_build_wire_envelope(
            action="CREATE_CUSTOMER",
            target_tab="Customers",
            nonce="KS-W2-BIND-001",
            actor_user_id="USR-1",
            actor_role="OWNER_ADMIN",
            payload_hash=hash_b,
            payload={"customer_id": "CUST-W2-001", "shop_name": "Mutated Shop"},
        )
        out = self._run_real_sheet_bridge_scenario([
            wire_orig,
            wire_diff_action,
            wire_diff_actor,
            wire_diff_hash,
            wire_orig,  # exact replay still succeeds idempotently
        ])
        self.assertEqual(out["responses"][0]["status"], "CONFIRMED")
        self.assertEqual(out["responses"][1]["status"], "REJECTED")
        self.assertEqual(out["responses"][1]["error_code"], "NONCE_ACTION_CONFLICT")
        self.assertEqual(out["responses"][1]["http_status"], 409)
        self.assertEqual(out["responses"][2]["status"], "REJECTED")
        self.assertEqual(out["responses"][2]["error_code"], "NONCE_ACTOR_CONFLICT")
        self.assertEqual(out["responses"][2]["http_status"], 409)
        self.assertEqual(out["responses"][3]["status"], "REJECTED")
        self.assertEqual(out["responses"][3]["error_code"], "NONCE_PAYLOAD_HASH_CONFLICT")
        self.assertEqual(out["responses"][3]["http_status"], 409)
        self.assertEqual(out["responses"][4]["status"], "CONFIRMED")
        self.assertTrue(out["responses"][4]["idempotent_replay"])

    def test_18_stage5_w5_non_primary_field_readback_corruption_quarantines_and_logs(self):
        # Corrupt column 2 (`shop_name`, NOT primary key col 0) during read-back
        wire_cust, _, _ = _python_build_wire_envelope(
            action="CREATE_CUSTOMER",
            target_tab="Customers",
            nonce="KS-W5-FIELD-CORRUPT-01",
            actor_user_id="USR-1",
            actor_role="OWNER_ADMIN",
            payload={"customer_id": "CUST-20261126-00101", "shop_name": "Shree Ganesh Traders"},
        )
        out = self._run_real_sheet_bridge_scenario(
            [wire_cust],
            corrupt_readback_tab="Customers",
            corrupt_readback_col=2,
        )
        res = out["responses"][0]
        self.assertEqual(res["status"], "RECOVERY_REQUIRED")
        self.assertEqual(res["error_code"], "BRIDGE_POST_WRITE_FAILURE")
        self.assertIn('Field "shop_name" mismatch', res["message"])
        self.assertEqual(len(out["sheetsData"]["ExceptionRegister"]), 2)

    def test_19_stage6_end_to_end_python_bridge_to_apps_script_vm_to_sheets(self):
        """
        Isolated cross-system verification (Stage 6):
        FastAPI AppsScriptBridge.execute_governed_write -> real HMAC envelope ->
        Node VM executing actual Apps Script files -> in-memory Google Sheets ->
        Python read-back verification, IdAllocations, and AuditLog. Zero live workbook writes.
        """
        from unittest.mock import patch
        import app.apps_script_bridge as bridge_mod

        bridge = AppsScriptBridge()
        captured_vm_out = {}
        e2e_nonce = f"KS-E2E-STAGE6-{uuid.uuid4().hex[:8].upper()}"

        def _fake_opener_open(req, timeout=10.0):
            # Pipe the exact raw bytes emitted by Python AppsScriptBridge straight into Node VM Apps Script!
            raw_body = req.data.decode("utf-8") if isinstance(req.data, (bytes, bytearray)) else str(req.data)
            vm_out = self._run_real_sheet_bridge_scenario([raw_body])
            captured_vm_out.clear()
            captured_vm_out.update(vm_out)
            resp_json = json.dumps(vm_out["responses"][0]).encode("utf-8")

            class _Resp:
                status = 200
                def read(self_inner):
                    return resp_json
                def __enter__(self_inner):
                    return self_inner
                def __exit__(self_inner, *args):
                    return False
                def getheaders(self_inner):
                    return [("Content-Type", "application/json")]

            return _Resp()

        class _FakeOpener:
            def open(self_inner, req, timeout=10.0):
                return _fake_opener_open(req, timeout=timeout)

        def _fake_get_records(tab_name, *args, **kwargs):
            _, _ = args, kwargs
            grid = (captured_vm_out.get("sheetsData") or {}).get(tab_name) or []
            if len(grid) < 2:
                return []
            headers = grid[0]
            rows = []
            for r in grid[1:]:
                rows.append({headers[i]: (r[i] if i < len(r) else "") for i in range(len(headers))})
            return rows

        with patch.object(bridge_mod, "SALES_APPS_SCRIPT_ENABLED", True), \
             patch.object(bridge_mod, "SALES_APPS_SCRIPT_WEBAPP_URL", "https://script.google.com/macros/s/AKfycbTestIsolatedOnly/exec"), \
             patch.object(bridge_mod, "SALES_APPS_SCRIPT_SHARED_SECRET", SHARED_SECRET), \
             patch.object(bridge_mod, "SALES_APPS_SCRIPT_TIMEOUT_SECONDS", 10.0), \
             patch("app.apps_script_bridge.urllib.request.build_opener", return_value=_FakeOpener()), \
             patch.object(bridge_mod.db, "get_records", side_effect=_fake_get_records), \
             patch.object(bridge_mod.db, "invalidate_tab_cache", return_value=None):
            res = bridge.execute_governed_write(
                action="UPDATE_CA_POLICY",
                target_tab="Settings",
                id_field="setting_key",
                payload={"setting_key": "GST_FILING_MODE", "setting_value": "MONTHLY"},
                nonce=e2e_nonce,
                actor_user_id="USR-1",
                actor_role="OWNER_ADMIN",
                correlation_id="CORR-E2E-STAGE6-001",
            )

        self.assertEqual(res.status, "CONFIRMED", f"Unexpected E2E result: {res}")
        self.assertEqual(res.nonce, e2e_nonce)
        self.assertEqual(len(captured_vm_out["sheetsData"]["Settings"]), 2)
        self.assertEqual(captured_vm_out["sheetsData"]["Settings"][1][0], "GST_FILING_MODE")
        self.assertEqual(captured_vm_out["sheetsData"]["Settings"][1][1], "MONTHLY")
        self.assertEqual(len(captured_vm_out["sheetsData"]["AuditLog"]), 2)
        self.assertEqual(captured_vm_out["sheetsData"]["AuditLog"][1][3], "UPDATE_CA_POLICY")

    def test_20_stage7_environment_cors_resolution_dev_staging_production(self):
        """Verify Stage 7 CORS config resolution across development, staging, and production."""
        from unittest.mock import patch
        import app.config as cfg

        # Development & staging permit localhost
        dev_origins = cfg.resolve_cors_origins("https://kawad-swad-sales-frontend.onrender.com", env="development")
        self.assertIn("http://localhost:3000", dev_origins)
        self.assertIn("https://kawad-swad-sales-frontend.onrender.com", dev_origins)

        staging_origins = cfg.resolve_cors_origins("https://kawad-swad-sales-frontend.onrender.com", env="staging")
        self.assertIn("http://localhost:3000", staging_origins)

        # Production strictly strips localhost and wildcards
        prod_origins = cfg.resolve_cors_origins(
            "https://kawad-swad-sales-frontend.onrender.com,http://localhost:3000,*",
            env="production",
        )
        self.assertEqual(prod_origins, ["https://kawad-swad-sales-frontend.onrender.com"])

        # assert_runtime_config() fails closed if production SALES_CORS_ORIGINS includes localhost or http://
        for bad_cors in (
            "https://kawad-swad-sales-frontend.onrender.com,http://localhost:3000",
            "http://127.0.0.1:3000",
            "http://kawad-swad-sales-frontend.onrender.com",
            "*",
        ):
            with patch.object(cfg, "SALES_ENV", "production"), \
                 patch.dict(os.environ, {"SALES_ENV": "production", "SALES_TESTING": "0", "SALES_JWT_SECRET": "a" * 40}, clear=False), \
                 patch.object(cfg, "SALES_CORS_ORIGINS", bad_cors):
                with self.assertRaises(RuntimeError, msg=f"Expected fail-closed for production CORS={bad_cors}"):
                    cfg.assert_runtime_config()


if __name__ == "__main__":
    unittest.main()
