/**
 * KAWAD SWAD ERP - CENTRAL ID ALLOCATOR
 * Wired to verified IdAllocations tab: [allocation_id, tab_name, allocated_id, nonce, created_at]
 * Enforces POL-002, REQ-101, Section 11.2 (LockService + idempotency nonce)
 */

/**
 * Internal caller-locked ID allocator.
 * Caller MUST already hold `LockService.getScriptLock()` for the full enclosing transaction.
 * This helper NEVER acquires or releases `ScriptLock`.
 *
 * @param {string} targetTabName
 * @param {string} nonce
 * @return {{status: string, allocation_id: string, allocated_id: string, tab_name: string, nonce: string}}
 */
function ksAllocateIdLocked_(targetTabName, nonce) {
  if (!targetTabName || !KS_CONFIG.ID_PREFIXES[targetTabName]) {
    throw new Error('Invalid or unapproved target table for ID allocation: ' + targetTabName);
  }
  if (!nonce || String(nonce).trim() === '') {
    throw new Error('Idempotency nonce is required for ID allocation.');
  }
  if (!LockService.getScriptLock().hasLock()) {
    throw new Error('LOCK_OWNERSHIP_VIOLATION: ksAllocateIdLocked_ requires caller-held ScriptLock.');
  }

  const ss = SpreadsheetApp.getActiveSpreadsheet();
  const allocSheet = ss.getSheetByName(KS_CONFIG.TABS.ID_ALLOCATIONS);
  const { headerMap } = ksGetHeaderMap_(allocSheet, KS_CONFIG.REQUIRED_HEADERS.IdAllocations);

  const lastRow = allocSheet.getLastRow();
  const cleanNonce = String(nonce).trim();
  const prefix = KS_CONFIG.ID_PREFIXES[targetTabName];
  const dateStamp = Utilities.formatDate(new Date(), KS_CONFIG.TIMEZONE, 'yyyyMMdd');

  let maxAllocSeq = 0;
  let maxTargetSeq = 0;

  if (lastRow >= 2) {
    const data = allocSheet.getRange(2, 1, lastRow - 1, allocSheet.getLastColumn()).getValues();
    const idxAllocId = headerMap['allocation_id'] - 1;
    const idxTab = headerMap['tab_name'] - 1;
    const idxAllocatedId = headerMap['allocated_id'] - 1;
    const idxNonce = headerMap['nonce'] - 1;

    for (let i = 0; i < data.length; i++) {
      const rowNonce = String(data[i][idxNonce] || '').trim();
      const rowTab = String(data[i][idxTab] || '').trim();

      // Idempotency check: return existing ID if this exact (tab_name + nonce) already succeeded
      if (rowNonce === cleanNonce && rowTab === targetTabName) {
        return {
          status: 'EXISTING_IDEMPOTENT',
          allocation_id: String(data[i][idxAllocId]),
          allocated_id: String(data[i][idxAllocatedId]),
          tab_name: targetTabName,
          nonce: cleanNonce
        };
      }

      // Track highest sequence numbers so IDs are never recycled (POL-002)
      const allocMatch = String(data[i][idxAllocId] || '').match(/(\d+)$/);
      if (allocMatch) maxAllocSeq = Math.max(maxAllocSeq, parseInt(allocMatch[1], 10));

      if (rowTab === targetTabName) {
        const targetMatch = String(data[i][idxAllocatedId] || '').match(/(\d+)$/);
        if (targetMatch) maxTargetSeq = Math.max(maxTargetSeq, parseInt(targetMatch[1], 10));
      }
    }
  }

  const nextAllocId = 'ALLOC-' + String(maxAllocSeq + 1).padStart(7, '0');
  const nextTargetId = prefix + '-' + dateStamp + '-' + String(maxTargetSeq + 1).padStart(5, '0');
  const nowIso = ksNowIso_();

  const allocRecord = {
    allocation_id: nextAllocId,
    tab_name: targetTabName,
    allocated_id: nextTargetId,
    nonce: cleanNonce,
    created_at: nowIso
  };

  ksAppendAndVerifyRow_(
    ss,
    KS_CONFIG.TABS.ID_ALLOCATIONS,
    allocRecord,
    'allocation_id',
    KS_CONFIG.REQUIRED_HEADERS.IdAllocations
  );

  return {
    status: 'NEW_ALLOCATED',
    allocation_id: nextAllocId,
    allocated_id: nextTargetId,
    tab_name: targetTabName,
    nonce: cleanNonce
  };
}

/**
 * Backward-compatible public ID allocator (`IdAllocator.js:7`).
 * - Existing 2-arg callers `ksAllocateId(tab, nonce)`: acquires & releases ScriptLock identically to original.
 * - Caller-locked callers `ksAllocateId(tab, nonce, { callerHoldsLock: true })`: delegates to
 *   `ksAllocateIdLocked_` without touching lock ownership.
 *
 * @param {string} targetTabName
 * @param {string} nonce
 * @param {{callerHoldsLock?: boolean}=} opts
 * @return {{status: string, allocation_id: string, allocated_id: string, tab_name: string, nonce: string}}
 */
function ksAllocateId(targetTabName, nonce, opts) {
  if (!targetTabName || !KS_CONFIG.ID_PREFIXES[targetTabName]) {
    throw new Error('Invalid or unapproved target table for ID allocation: ' + targetTabName);
  }
  if (!nonce || String(nonce).trim() === '') {
    throw new Error('Idempotency nonce is required for ID allocation.');
  }

  const callerHoldsLock = Boolean(opts && opts.callerHoldsLock === true);
  if (callerHoldsLock) {
    return ksAllocateIdLocked_(targetTabName, nonce);
  }

  const lock = LockService.getScriptLock();
  lock.waitLock(KS_CONFIG.LOCK_TIMEOUT_MS);

  try {
    return ksAllocateIdLocked_(targetTabName, nonce);
  } finally {
    lock.releaseLock();
  }
}
