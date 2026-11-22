/**
 * TX-FINAL-04: Frontend UNKNOWN-Outcome Locking, Nonce Preservation & Persistence Utilities
 *
 * Ensures that when ANY governed mutation enters an UNKNOWN or RECOVERY_REQUIRED outcome:
 * 1. Transaction-affecting form inputs are locked against editing.
 * 2. Submit and reset/escape controls are disabled until outcome is verified.
 * 3. Editing attempts cannot clear or rotate the preserved idempotency nonce.
 * 4. Original nonce and payload fingerprint survive component remounts/navigation via sessionStorage.
 * 5. State can only be unlocked after verified CONFIRMED_RECORDED / RECONCILED status or
 *    successful same-nonce recovery retry completion.
 */

import { useCallback, useEffect, useState } from 'react';
import type { UnknownOutcomeState } from '../services/api';

const STORAGE_PREFIX = 'ks_tx_unknown_lock_v1:';

export interface PersistedUnknownLockRecord {
  outcome: UnknownOutcomeState;
  preservedNonce: string;
  payloadFingerprint?: string;
  lockedAt: string;
}

function getSafeSessionStorage(): Storage | null {
  try {
    if (typeof window !== 'undefined' && window.sessionStorage) {
      return window.sessionStorage;
    }
  } catch {
    // Ignore restricted storage environments (SSR/test/private mode)
  }
  return null;
}

export function isOutcomeLocked(outcome: UnknownOutcomeState | null | undefined): boolean {
  return Boolean(outcome && outcome.nonce);
}

/**
 * Guard helper for form field onChange handlers that would otherwise reset a draft nonce.
 * While an UNKNOWN / RECOVERY_REQUIRED outcome is active, payload edits MUST NOT clear or
 * rotate the preserved nonce.
 */
export function shouldBlockDraftNonceReset(outcome: UnknownOutcomeState | null | undefined): boolean {
  return isOutcomeLocked(outcome);
}

/**
 * Stable lightweight fingerprint for verifying that a preserved payload has not drifted
 * across same-nonce retries.
 */
export function computePayloadFingerprint(payload: unknown): string {
  try {
    return JSON.stringify(payload ?? null);
  } catch {
    return String(payload ?? '');
  }
}

export function persistUnknownOutcome(
  scopeKey: string,
  outcome: UnknownOutcomeState,
  payloadFingerprint?: string
): void {
  const storage = getSafeSessionStorage();
  if (!storage || !scopeKey || !outcome?.nonce) return;
  try {
    const rec: PersistedUnknownLockRecord = {
      outcome,
      preservedNonce: outcome.nonce,
      payloadFingerprint,
      lockedAt: new Date().toISOString(),
    };
    storage.setItem(`${STORAGE_PREFIX}${scopeKey}`, JSON.stringify(rec));
  } catch {
    // Ignore quota errors
  }
}

export function loadPersistedUnknownOutcome(scopeKey: string): PersistedUnknownLockRecord | null {
  const storage = getSafeSessionStorage();
  if (!storage || !scopeKey) return null;
  try {
    const raw = storage.getItem(`${STORAGE_PREFIX}${scopeKey}`);
    if (!raw) return null;
    const parsed = JSON.parse(raw) as PersistedUnknownLockRecord;
    if (
      parsed &&
      parsed.outcome &&
      typeof parsed.outcome.nonce === 'string' &&
      parsed.outcome.nonce.trim()
    ) {
      return parsed;
    }
  } catch {
    // Ignore malformed entries
  }
  return null;
}

export function clearPersistedUnknownOutcome(scopeKey: string): void {
  const storage = getSafeSessionStorage();
  if (!storage || !scopeKey) return;
  try {
    storage.removeItem(`${STORAGE_PREFIX}${scopeKey}`);
  } catch {
    // Ignore storage errors
  }
}

/**
 * Reusable React hook that manages a view's UNKNOWN/RECOVERY_REQUIRED lock state with
 * automatic sessionStorage persistence so navigating away or remounting cannot silently
 * drop the lock or rotate the preserved nonce.
 */
export function useUnknownOutcomeGuard(scopeKey: string) {
  const [unknownOutcome, setUnknownOutcomeInternal] = useState<UnknownOutcomeState | null>(() => {
    const restored = loadPersistedUnknownOutcome(scopeKey);
    return restored ? restored.outcome : null;
  });

  const [payloadFingerprint, setPayloadFingerprint] = useState<string | undefined>(() => {
    const restored = loadPersistedUnknownOutcome(scopeKey);
    return restored?.payloadFingerprint;
  });

  useEffect(() => {
    if (unknownOutcome && unknownOutcome.nonce) {
      persistUnknownOutcome(scopeKey, unknownOutcome, payloadFingerprint);
    } else {
      clearPersistedUnknownOutcome(scopeKey);
    }
  }, [scopeKey, unknownOutcome, payloadFingerprint]);

  const lockWithUnknownOutcome = useCallback(
    (nextOutcome: UnknownOutcomeState, payload?: unknown) => {
      const fp = payload !== undefined ? computePayloadFingerprint(payload) : undefined;
      setPayloadFingerprint(fp);
      setUnknownOutcomeInternal(nextOutcome);
      persistUnknownOutcome(scopeKey, nextOutcome, fp);
    },
    [scopeKey]
  );

  const clearAfterVerifiedResolution = useCallback(() => {
    setUnknownOutcomeInternal(null);
    setPayloadFingerprint(undefined);
    clearPersistedUnknownOutcome(scopeKey);
  }, [scopeKey]);

  const setUnknownOutcome = useCallback(
    (next: UnknownOutcomeState | null, payload?: unknown) => {
      if (next && next.nonce) {
        lockWithUnknownOutcome(next, payload);
      } else {
        clearAfterVerifiedResolution();
      }
    },
    [lockWithUnknownOutcome, clearAfterVerifiedResolution]
  );

  return {
    unknownOutcome,
    isOutcomeLocked: isOutcomeLocked(unknownOutcome),
    preservedNonce: unknownOutcome?.nonce || null,
    payloadFingerprint,
    setUnknownOutcome,
    lockWithUnknownOutcome,
    clearAfterVerifiedResolution,
  };
}
