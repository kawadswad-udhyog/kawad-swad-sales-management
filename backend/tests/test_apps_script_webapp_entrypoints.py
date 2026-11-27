"""
Kawad Swad ERP — Apps Script Web App Entry Point & Handler Architecture Verification Suite.

Verifies against the actual `apps_script/` source files:
  1. Exactly ONE global `doGet(e)` and ONE global `doPost(e)` exist across all `apps_script/*.js`
     files (both executable in V8/Node VM and at source declaration level), both owned by
     `WebAppBridge.js` (and zero `function doPost` / `function doGet` text in
     `WebAppBridge_BootstrapIntegration.js`).
  2. All 42 `.js` files in `apps_script/` parse cleanly with zero syntax errors and zero
     collisions across the 6 integrated bridge/bootstrap files, while preserving all 44 inventoried
     project files (including `DatabaseReconciliationFix.js`, `ErpSidebar.html`, `appsscript.json`)
     matching `SOURCE_INVENTORY_AND_SHA256.txt` and `MERGED_SHA256_MANIFEST.md`.
  3. `doGet(e)` returns clean read-only JSON health/status (HEALTHY when configured, DEGRADED
     when shared secret is unset/weak), never exposes secrets or reads spreadsheet business rows,
     and fails closed (HTTP 405 METHOD_NOT_ALLOWED) when any governed/mutating action such as
     `BOOTSTRAP_FIRST_OWNER` or `CREATE_SALE` is attempted via HTTP GET.
  4. `doPost(e)` preserves mandatory HMAC-SHA256 verification, isolated `BOOTSTRAP_FIRST_OWNER`
     routing, and governed action routing (`UPDATE_CA_POLICY` -> `Settings`, etc.) end-to-end.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
import unittest
from datetime import datetime, timezone

BACKEND_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
REPO_ROOT = os.path.abspath(os.path.join(BACKEND_DIR, ".."))
APPS_SCRIPT_DIR = os.path.join(REPO_ROOT, "apps_script")
MERGED_DIR = os.path.join(REPO_ROOT, "apps_script_patch", "first_owner_bootstrap", "merged_bound_files")

if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

os.environ.setdefault("SALES_TESTING", "1")
from app.apps_script_bridge import AppsScriptBridge  # noqa: E402
from app.transaction_safety import compute_deterministic_payload_hash  # noqa: E402

_TEST_SHARED_SECRET = "KsWebAppEntrypointTestSharedSecret_2026_AtLeast32Chars!"


def _run_node_vm(script: str, payload: dict) -> dict:
    proc = subprocess.run(
        ["node", "-e", script],
        input=json.dumps(payload),
        text=True,
        capture_output=True,
        check=True,
    )
    return json.loads(proc.stdout)


class TestAppsScriptWebAppEntryPoints(unittest.TestCase):
    def test_01_single_authoritative_doget_and_dopost_and_full_syntax_check(self):
        node_script = r"""
const fs = require('fs'), path = require('path'), vm = require('vm');
const input = JSON.parse(fs.readFileSync(0, 'utf8'));
const files = fs.readdirSync(input.appsDir).filter(f => f.endsWith('.js')).sort();
const syntaxErrors = [];
const execDoGet = [];
const execDoPost = [];
const rawDoGet = [];
const rawDoPost = [];

for (const f of files) {
  const src = fs.readFileSync(path.join(input.appsDir, f), 'utf8');
  try {
    new vm.Script(src, { filename: f });
  } catch (e) {
    syntaxErrors.push({ file: f, error: e.message });
    continue;
  }
  const lines = src.split('\n');
  lines.forEach((line, idx) => {
    if (/\bfunction\s+doGet\s*\(/.test(line)) rawDoGet.push(`${f}:${idx + 1}`);
    if (/\bfunction\s+doPost\s*\(/.test(line)) rawDoPost.push(`${f}:${idx + 1}`);
  });
  const ctx = vm.createContext({ console });
  vm.runInContext(src, ctx, { filename: f });
  if (typeof ctx.doGet === 'function') execDoGet.push(f);
  if (typeof ctx.doPost === 'function') execDoPost.push(f);
}

process.stdout.write(JSON.stringify({
  jsCount: files.length,
  syntaxErrors,
  execDoGet,
  execDoPost,
  rawDoGet,
  rawDoPost,
}));
"""
        res = _run_node_vm(node_script, {"appsDir": APPS_SCRIPT_DIR})
        self.assertEqual(res["jsCount"], 42)
        self.assertEqual(res["syntaxErrors"], [])
        self.assertEqual(res["execDoGet"], ["WebAppBridge.js"])
        self.assertEqual(res["execDoPost"], ["WebAppBridge.js"])
        self.assertEqual(len(res["rawDoGet"]), 1)
        self.assertTrue(res["rawDoGet"][0].startswith("WebAppBridge.js:"))
        self.assertEqual(len(res["rawDoPost"]), 1)
        self.assertTrue(res["rawDoPost"][0].startswith("WebAppBridge.js:"))

    def test_02_source_inventory_and_merged_manifest_preserve_all_files_and_hashes(self):
        inv_path = os.path.join(APPS_SCRIPT_DIR, "SOURCE_INVENTORY_AND_SHA256.txt")
        self.assertTrue(os.path.isfile(inv_path))
        inv_entries = {}
        with open(inv_path, "r", encoding="utf-8") as f:
            for line in f:
                m = re.match(r"^FILE:\s+(.+?)\tBYTES:\s+(\d+)\tSHA256:\s+([0-9a-f]{64})\tSTATUS:", line.strip())
                if m:
                    inv_entries[m.group(1)] = (int(m.group(2)), m.group(3))

        # All 44 bound project files preserved (including DatabaseReconciliationFix.js)
        self.assertEqual(len(inv_entries), 44)
        self.assertIn("DatabaseReconciliationFix.js", inv_entries)
        self.assertIn("ErpSidebar.html", inv_entries)
        self.assertIn("appsscript.json", inv_entries)
        self.assertIn("WebAppBridge.js", inv_entries)
        self.assertIn("WebAppBridge_BootstrapIntegration.js", inv_entries)
        self.assertIn("BootstrapOwnerHandler.js", inv_entries)

        for fname, (exp_bytes, exp_sha) in inv_entries.items():
            fpath = os.path.join(APPS_SCRIPT_DIR, fname)
            self.assertTrue(os.path.isfile(fpath), f"Missing inventoried file: {fname}")
            with open(fpath, "rb") as fh:
                raw = fh.read()
            self.assertEqual(len(raw), exp_bytes, f"Byte count mismatch for {fname}")
            self.assertEqual(hashlib.sha256(raw).hexdigest(), exp_sha, f"SHA-256 mismatch for {fname}")

        # Verify mirrored merged_bound_files parity + MERGED_SHA256_MANIFEST.md
        merged_manifest = os.path.join(MERGED_DIR, "MERGED_SHA256_MANIFEST.md")
        with open(merged_manifest, "r", encoding="utf-8") as f:
            manifest_text = f.read()
        for fname in (
            "Config.js",
            "IdAllocator.js",
            "AuditAndExceptions.js",
            "BootstrapOwnerHandler.js",
            "WebAppBridge_BootstrapIntegration.js",
            "WebAppBridge.js",
        ):
            p1 = os.path.join(APPS_SCRIPT_DIR, fname)
            p2 = os.path.join(MERGED_DIR, fname)
            with open(p1, "rb") as f1, open(p2, "rb") as f2:
                b1, b2 = f1.read(), f2.read()
            self.assertEqual(b1, b2, f"apps_script/{fname} diverged from merged_bound_files/{fname}")
            sha = hashlib.sha256(b1).hexdigest()
            self.assertIn(f"- `{fname}` | bytes={len(b1)} | sha256=`{sha}`", manifest_text)

    def test_03_doget_health_status_and_fail_closed_method_guard(self):
        node_script = r"""
const fs = require('fs'), path = require('path'), vm = require('vm');
const input = JSON.parse(fs.readFileSync(0, 'utf8'));

function runWithProps(propsMap) {
  let spreadsheetAccessed = false;
  const ctx = vm.createContext({
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
    PropertiesService: {
      getScriptProperties: () => ({
        getProperty: (k) => (Object.prototype.hasOwnProperty.call(propsMap, k) ? propsMap[k] : null)
      })
    },
    Utilities: {
      formatDate: () => '2026-11-27T18:24:00+05:30'
    },
    SpreadsheetApp: {
      getActiveSpreadsheet: () => {
        spreadsheetAccessed = true;
        throw new Error('doGet must not touch SpreadsheetApp');
      }
    },
    ContentService: {
      MimeType: { JSON: 'application/json' },
      createTextOutput: (txt) => ({
        _txt: txt,
        _mime: null,
        setMimeType(m) { this._mime = m; return this; },
        getContent() { return this._txt; },
        getMimeType() { return this._mime; }
      })
    }
  });

  for (const f of ['Config.js', 'IdAllocator.js', 'AuditAndExceptions.js', 'BootstrapOwnerHandler.js', 'WebAppBridge_BootstrapIntegration.js', 'WebAppBridge.js']) {
    vm.runInContext(fs.readFileSync(path.join(input.appsDir, f), 'utf8'), ctx, { filename: f });
  }

  const outDefault = ctx.doGet();
  const outHealth = ctx.doGet({ parameter: { action: 'health' } });
  const outStatus = ctx.doGet({ parameter: { action: 'status' } });
  const outPing = ctx.doGet({ parameter: { action: 'ping' } });
  const outBootstrapGet = ctx.doGet({ parameter: { action: 'BOOTSTRAP_FIRST_OWNER' } });
  const outWriteGet = ctx.doGet({ parameter: { action: 'CREATE_SALE' } });

  return {
    spreadsheetAccessed,
    mimeDefault: outDefault.getMimeType(),
    defaultResp: JSON.parse(outDefault.getContent()),
    healthResp: JSON.parse(outHealth.getContent()),
    statusResp: JSON.parse(outStatus.getContent()),
    pingResp: JSON.parse(outPing.getContent()),
    bootstrapGetResp: JSON.parse(outBootstrapGet.getContent()),
    writeGetResp: JSON.parse(outWriteGet.getContent()),
    rawDefaultText: outDefault.getContent(),
  };
}

const healthy = runWithProps({
  SALES_APPS_SCRIPT_SHARED_SECRET: input.sharedSecret,
  KS_OWNER_BOOTSTRAP_TOKEN_HASH: 'f'.repeat(64),
});
const degraded = runWithProps({});

process.stdout.write(JSON.stringify({ healthy, degraded }));
"""
        res = _run_node_vm(node_script, {"appsDir": APPS_SCRIPT_DIR, "sharedSecret": _TEST_SHARED_SECRET})

        # Healthy state
        h = res["healthy"]
        self.assertFalse(h["spreadsheetAccessed"], "doGet must never touch SpreadsheetApp")
        self.assertEqual(h["mimeDefault"], "application/json")
        for key in ("defaultResp", "healthResp", "statusResp", "pingResp"):
            body = h[key]
            self.assertTrue(body["ok"])
            self.assertEqual(body["status"], "HEALTHY")
            self.assertEqual(body["service"], "kawad-swad-erp-apps-script-bridge")
            self.assertEqual(body["contract_version"], "2.0")
            self.assertEqual(body["auth_mode"], "HMAC-SHA-256")
            self.assertTrue(body["bridge_ready"])
            self.assertTrue(body["verifier_loaded"])
            self.assertTrue(body["strict_audit_loaded"])
            self.assertTrue(body["bootstrap_handler_loaded"])

        # Zero secrets leaked in output
        self.assertNotIn(_TEST_SHARED_SECRET, h["rawDefaultText"])
        self.assertNotIn("f" * 16, h["rawDefaultText"])

        # Mutating / governed actions via GET fail closed with HTTP 405
        for key in ("bootstrapGetResp", "writeGetResp"):
            rej = h[key]
            self.assertFalse(rej["ok"])
            self.assertEqual(rej["status"], "REJECTED")
            self.assertEqual(rej["error_code"], "METHOD_NOT_ALLOWED")
            self.assertEqual(rej["http_status"], 405)

        # Degraded state when shared secret is absent
        d = res["degraded"]
        self.assertFalse(d["spreadsheetAccessed"])
        self.assertTrue(d["defaultResp"]["ok"])
        self.assertEqual(d["defaultResp"]["status"], "DEGRADED")
        self.assertFalse(d["defaultResp"]["bridge_ready"])

    def test_04_dopost_governed_routing_and_bootstrap_routing_preserved(self):
        # Signed BOOTSTRAP_FIRST_OWNER envelope
        bootstrap_secret = "BootstrapTokenForEntrypointRoutingCheck_2026_32Plus!"
        bootstrap_hash = hashlib.sha256(bootstrap_secret.encode("utf-8")).hexdigest()
        pw_hash = "pbkdf2:sha256:100000$" + ("a" * 32) + "$" + ("b" * 64)
        boot_payload = {
            "bootstrap_token_digest": bootstrap_hash,
            "username": "owner.boot",
            "full_name": "Kawad Owner",
            "password_hash": pw_hash,
            "role": "OWNER_ADMIN",
            "must_change_password": "false",
            "email": "owner@example.com",
            "mobile": "9999999999",
        }
        envelope_boot = {
            "contract_version": "2.0",
            "action": "BOOTSTRAP_FIRST_OWNER",
            "target_tab": "Users",
            "nonce": "NONCE-ENTRYPOINT-BOOT-001",
            "correlation_id": "CORR-ENTRYPOINT-BOOT-001",
            "transaction_id": "TX-ENTRYPOINT-BOOT-001",
            "attempt_number": 1,
            "payload_hash": compute_deterministic_payload_hash(
                action="BOOTSTRAP_FIRST_OWNER",
                target_tab="Users",
                actor_user_id="SYSTEM_BOOTSTRAP",
                actor_role="OWNER_ADMIN",
                payload=boot_payload,
            ),
            "actor_user_id": "SYSTEM_BOOTSTRAP",
            "actor_role": "OWNER_ADMIN",
            "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "payload": boot_payload,
        }
        canonical_boot = json.dumps(envelope_boot, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
        wire_boot = json.dumps({
            "contract_version": "2.0",
            "signature_alg": "HMAC-SHA-256",
            "signature": AppsScriptBridge.sign_envelope(canonical_boot, _TEST_SHARED_SECRET),
            "canonical_envelope": canonical_boot,
        })

        # Signed governed UPDATE_CA_POLICY envelope using the exact USR-YYYYMMDD-00001 allocated by bootstrap
        expected_owner_id = f"USR-{datetime.now(timezone.utc).strftime('%Y%m%d')}-00001"
        payload_settings = {"setting_key": "tax_mode", "setting_value": "GST_STANDARD"}
        payload_hash = compute_deterministic_payload_hash(
            action="UPDATE_CA_POLICY",
            target_tab="Settings",
            actor_user_id=expected_owner_id,
            actor_role="OWNER_ADMIN",
            payload=payload_settings,
        )
        envelope_settings = {
            "contract_version": "2.0",
            "action": "UPDATE_CA_POLICY",
            "target_tab": "Settings",
            "nonce": "NONCE-ENTRYPOINT-SETTINGS-001",
            "correlation_id": "CORR-ENTRYPOINT-001",
            "transaction_id": "TX-ENTRYPOINT-001",
            "attempt_number": 1,
            "payload_hash": payload_hash,
            "actor_user_id": expected_owner_id,
            "actor_role": "OWNER_ADMIN",
            "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "payload": payload_settings,
        }
        canonical_settings = json.dumps(envelope_settings, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
        wire_settings = json.dumps({
            "contract_version": "2.0",
            "signature_alg": "HMAC-SHA-256",
            "signature": AppsScriptBridge.sign_envelope(canonical_settings, _TEST_SHARED_SECRET),
            "canonical_envelope": canonical_settings,
        })

        node_script = r"""
const fs = require('fs'), path = require('path'), vm = require('vm'), crypto = require('crypto');
const input = JSON.parse(fs.readFileSync(0, 'utf8'));

class FakeSheet {
  constructor(name, rows) { this.name = name; this.rows = rows.map(r => r.slice()); }
  getName() { return this.name; }
  getLastRow() { return this.rows.length; }
  getLastColumn() { return this.rows.length ? this.rows[0].length : 0; }
  getDataRange() { return this.getRange(1, 1, this.getLastRow(), this.getLastColumn()); }
  setFrozenRows() {}
  getRange(r, c, nr = 1, nc = 1) {
    const sh = this;
    return {
      getValues() {
        const out = [];
        for (let i = 0; i < nr; i++) {
          const row = sh.rows[r - 1 + i] || [];
          const slice = [];
          for (let j = 0; j < nc; j++) slice.push(row[c - 1 + j] === undefined ? '' : row[c - 1 + j]);
          out.push(slice);
        }
        return out;
      },
      setValues(vals) {
        for (let i = 0; i < vals.length; i++) {
          const idx = r - 1 + i;
          while (sh.rows.length <= idx) sh.rows.push(new Array(sh.getLastColumn()).fill(''));
          for (let j = 0; j < vals[i].length; j++) sh.rows[idx][c - 1 + j] = vals[i][j];
        }
      }
    };
  }
  appendRow(row) { this.rows.push(row.slice()); }
}

const props = {
  SALES_APPS_SCRIPT_SHARED_SECRET: input.sharedSecret,
  KS_OWNER_BOOTSTRAP_TOKEN_HASH: input.bootstrapHash,
  KS_OWNER_BOOTSTRAP_EXPIRES_AT: '2099-01-01T00:00:00Z',
};
let lockHeld = false;
const sheets = {
  Users: new FakeSheet('Users', [['user_id','full_name','username','role','mobile','email','active','created_at','notes','employment_type','designation','department','reporting_manager_id','joining_date','employment_status','salary_frequency','salary_structure_id','address','emergency_contact','bank_details','document_references','updated_at','created_by','effective_from','effective_to']]),
  AuthUsers: new FakeSheet('AuthUsers', [['auth_id','user_id','username','password_hash','role','active','created_at','must_change_password','sessions_revoked_at']]),
  AuditLog: new FakeSheet('AuditLog', [['audit_id','event_datetime','actor_user_id','action','entity_type','entity_id','field_changed','old_value','new_value','reason','approved_by_user_id','related_record_id']]),
  IdAllocations: new FakeSheet('IdAllocations', [['allocation_id','tab_name','allocated_id','nonce','created_at']]),
  ExceptionRegister: new FakeSheet('ExceptionRegister', [['exception_id','created_at','severity','source_function','tab_name','reference_id','error_message','payload_json','assigned_owner','due_date','status','resolution_notes','resolved_by','resolved_at']]),
  Settings: new FakeSheet('Settings', [['setting_key','setting_value','created_at','created_by','nonce']]),
};

const ctx = vm.createContext({
  console, Date, Math, JSON, Object, Array, String, Number, Boolean, RegExp, Error, parseInt, isNaN,
  PropertiesService: {
    getScriptProperties: () => ({
      getProperty: (k) => (Object.prototype.hasOwnProperty.call(props, k) ? props[k] : null),
      setProperty: (k, v) => { props[k] = String(v); },
      setProperties: (obj) => { for (const [k, v] of Object.entries(obj)) props[k] = String(v); },
      deleteProperty: (k) => { delete props[k]; }
    })
  },
  LockService: {
    getScriptLock: () => ({
      waitLock: () => { lockHeld = true; },
      tryLock: () => { lockHeld = true; return true; },
      hasLock: () => lockHeld,
      releaseLock: () => { lockHeld = false; }
    })
  },
  SpreadsheetApp: {
    getActiveSpreadsheet: () => ({ getSheetByName: (n) => sheets[n] || null }),
    flush: () => {}
  },
  Utilities: {
    Charset: { UTF_8: 'UTF-8' },
    DigestAlgorithm: { SHA_256: 'SHA-256' },
    getUuid: () => crypto.randomUUID(),
    formatDate: (d, _tz, fmt) => {
      const y = d.getUTCFullYear();
      const m = String(d.getUTCMonth() + 1).padStart(2, '0');
      const day = String(d.getUTCDate()).padStart(2, '0');
      if (fmt === 'yyyyMMdd') return `${y}${m}${day}`;
      return d.toISOString();
    },
    computeHmacSha256Signature: (msg, sec) => Array.from(crypto.createHmac('sha256', Buffer.from(sec, 'utf8')).update(Buffer.from(msg, 'utf8')).digest()).map(b => b > 127 ? b - 256 : b),
    computeDigest: (_alg, msg) => Array.from(crypto.createHash('sha256').update(Buffer.from(msg, 'utf8')).digest()).map(b => b > 127 ? b - 256 : b),
  },
  Session: {
    getActiveUser: () => ({ getEmail: () => 'owner@example.com' }),
    getEffectiveUser: () => ({ getEmail: () => 'owner@example.com' }),
  },
  ContentService: {
    MimeType: { JSON: 'application/json' },
    createTextOutput: (txt) => ({ _t: txt, setMimeType() { return this; }, getContent() { return this._t; } })
  }
});

for (const f of ['Config.js', 'SafeWriter.js', 'IdAllocator.js', 'AuditAndExceptions.js', 'BootstrapOwnerHandler.js', 'WebAppBridge_BootstrapIntegration.js', 'WebAppBridge.js']) {
  vm.runInContext(fs.readFileSync(path.join(input.appsDir, f), 'utf8'), ctx, { filename: f });
}

const bootRes = JSON.parse(ctx.doPost({ postData: { contents: input.wireBoot } }).getContent());
const settingsRes = JSON.parse(ctx.doPost({ postData: { contents: input.wireSettings } }).getContent());
const unsignedRes = JSON.parse(ctx.doPost({ postData: { contents: JSON.stringify({ action: 'UPDATE_CA_POLICY' }) } }).getContent());

process.stdout.write(JSON.stringify({
  bootRes,
  settingsRes,
  unsignedRes,
  lockHeld,
  usersRows: sheets.Users.rows.length,
  settingsRows: sheets.Settings.rows.length,
}));
"""
        res = _run_node_vm(
            node_script,
            {
                "appsDir": APPS_SCRIPT_DIR,
                "sharedSecret": _TEST_SHARED_SECRET,
                "bootstrapHash": bootstrap_hash,
                "wireBoot": wire_boot,
                "wireSettings": wire_settings,
            },
        )
        self.assertEqual(res["bootRes"]["status"], "CONFIRMED", res["bootRes"])
        self.assertEqual(res["bootRes"]["allocated_id"], expected_owner_id)
        self.assertEqual(res["settingsRes"]["status"], "CONFIRMED", res["settingsRes"])
        self.assertEqual(res["settingsRes"]["target_tab"], "Settings")
        self.assertEqual(res["unsignedRes"]["status"], "REJECTED")
        self.assertEqual(res["usersRows"], 2)
        self.assertEqual(res["settingsRows"], 2)
        self.assertFalse(res["lockHeld"])


if __name__ == "__main__":
    unittest.main()
