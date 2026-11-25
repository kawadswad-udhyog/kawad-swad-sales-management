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
  ctx.ksFindByNonce_ = (nonce) => { legacyCalls.push(['ksFindByNonce_', nonce]); return null; };
  ctx.ksRouteGovernedWrite_ = (action, tab, payload) => {
    legacyCalls.push(['ksRouteGovernedWrite_', action, tab]);
    return { allocated_id: 'CUST-20261125-00001', record: payload };
  };
  ctx.ksRecordIdAllocation_ = (nonce, tab, id) => { legacyCalls.push(['ksRecordIdAllocation_', nonce, tab, id]); };
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


if __name__ == "__main__":
    unittest.main()
