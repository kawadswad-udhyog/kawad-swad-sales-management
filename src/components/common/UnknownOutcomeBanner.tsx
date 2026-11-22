import React, { useEffect, useState } from 'react';
import {
  checkV2TransactionStatus,
  TransactionStatusResponse,
  UnknownOutcomeState,
} from '../../services/api';

interface UnknownOutcomeBannerProps {
  outcome: UnknownOutcomeState | null;
  onRetry?: () => void;
  onConfirmedRecorded?: (status: TransactionStatusResponse) => void;
  onDismiss?: () => void;
  persistenceDegraded?: boolean;
  persistenceFailureReason?: string | null;
  payloadFingerprint?: string;
  fingerprintMismatchError?: string | null;
}

const STATUS_CHECK_COOLDOWN_MS = 2000;

/**
 * Reusable 504 / PENDING_UNKNOWN / RECOVERY_REQUIRED transaction safety banner (TX-FINAL-04 + 51B-1R-F).
 * - Retains exact client nonce, correlation_id, and canonical payload fingerprint without clearing user inputs.
 * - Keeps form inputs and new submissions locked while outcome is UNKNOWN, RECOVERY_REQUIRED, or persistence-degraded.
 * - Explicitly displays visible Safety-Degraded Mode warning whenever sessionStorage persistence fails,
 *   is unavailable, or stored lock data is corrupted (never assuming reload safety).
 * - Blocks retrying until GET /api/v2/transactions/status/{nonce} confirms
 *   `NOT_FOUND_SAFE_TO_RETRY_SAME_NONCE` (`safe_to_retry_same_nonce === true`).
 * - Permanently disables automatic retry for `CONFIRMED_RECORDED`, `RECONCILED`,
 *   `RECOVERY_REQUIRED`, or payload fingerprint mismatch.
 * - Disallows casual dismissal while unresolved; unlock is only enabled after verified
 *   `CONFIRMED_RECORDED` or `RECONCILED` status.
 */
export const UnknownOutcomeBanner: React.FC<UnknownOutcomeBannerProps> = ({
  outcome,
  onRetry,
  onConfirmedRecorded,
  onDismiss,
  persistenceDegraded: propPersistenceDegraded,
  persistenceFailureReason: propPersistenceFailureReason,
  payloadFingerprint: propPayloadFingerprint,
  fingerprintMismatchError,
}) => {
  const [checking, setChecking] = useState(false);
  const [statusResult, setStatusResult] = useState<TransactionStatusResponse | null>(null);
  const [checkError, setCheckError] = useState<string | null>(null);
  const [cooldownActive, setCooldownActive] = useState(false);

  // Reset local verification result when a new outcome/nonce arrives
  useEffect(() => {
    setStatusResult(null);
    setCheckError(null);
  }, [outcome?.nonce, outcome?.correlationId, outcome?.recoveryRequired]);

  if (!outcome) return null;

  const isPersistenceDegraded = Boolean(
    propPersistenceDegraded || outcome.persistenceDegraded || outcome.reloadSafe === false
  );
  const failureReason = propPersistenceFailureReason || outcome.persistenceFailureReason || null;
  const effectiveFingerprint = propPayloadFingerprint || outcome.payloadFingerprint || null;

  const handleCheckStatus = async () => {
    if (!outcome.nonce || checking || cooldownActive) return;
    setChecking(true);
    setCheckError(null);
    try {
      const res = await checkV2TransactionStatus(outcome.nonce, outcome.correlationId);
      setStatusResult(res);
      if (
        (res.status === 'CONFIRMED_RECORDED' || res.status === 'RECONCILED') &&
        onConfirmedRecorded
      ) {
        onConfirmedRecorded(res);
      }
    } catch (err: unknown) {
      setCheckError(
        err instanceof Error
          ? err.message
          : 'Could not reach transaction status endpoint. Keep your form inputs locked and try checking again.'
      );
    } finally {
      setChecking(false);
      setCooldownActive(true);
      setTimeout(() => setCooldownActive(false), STATUS_CHECK_COOLDOWN_MS);
    }
  };

  const isVerifiedResolved =
    statusResult?.status === 'CONFIRMED_RECORDED' || statusResult?.status === 'RECONCILED';
  const isConfirmed = isVerifiedResolved;
  const isRecoveryRequired =
    Boolean(outcome.recoveryRequired) ||
    outcome.transactionState === 'RECOVERY_REQUIRED' ||
    statusResult?.status === 'RECOVERY_REQUIRED';
  const isInProgress = statusResult?.status === 'IN_PROGRESS';
  const hasPayloadMismatch = Boolean(fingerprintMismatchError);
  const isSafeRetry =
    !isRecoveryRequired &&
    !hasPayloadMismatch &&
    Boolean(outcome.nonce) &&
    statusResult?.status === 'NOT_FOUND_SAFE_TO_RETRY_SAME_NONCE' &&
    statusResult?.safe_to_retry_same_nonce === true;

  const palette = isConfirmed
    ? { bg: '#ecfdf5', border: '#6ee7b7', text: '#065f46' }
    : isRecoveryRequired || hasPayloadMismatch
    ? { bg: '#fef2f2', border: '#f87171', text: '#991b1b' }
    : { bg: '#fffbeb', border: '#f59e0b', text: '#92400e' };

  const heading = isConfirmed
    ? statusResult?.status === 'RECONCILED'
      ? 'Transaction Reconciled by Administrator'
      : 'Transaction Confirmed Recorded in Google Sheets'
    : isRecoveryRequired
    ? 'Recovery Required — Automatic Retry Disabled (Form Locked)'
    : isInProgress
    ? 'Transaction Still Processing on Server (Form Locked)'
    : isSafeRetry
    ? 'Verified Not Recorded — Safe to Retry with Same Nonce'
    : 'Outcome Unknown — Check Transaction Status Before Retrying (Form Locked)';

  return (
    <div
      role="alert"
      data-tx-lock-banner="true"
      data-tx-nonce={outcome.nonce}
      data-tx-persistence-degraded={isPersistenceDegraded ? 'true' : 'false'}
      data-tx-payload-fingerprint={effectiveFingerprint || ''}
      style={{
        background: palette.bg,
        border: `1px solid ${palette.border}`,
        borderRadius: 10,
        padding: '12px 14px',
        marginBottom: 14,
        color: palette.text,
        fontSize: 13,
      }}
    >
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: 10 }}>
        <div>
          <div style={{ fontWeight: 700, marginBottom: 4 }}>
            {heading}
            {outcome.actionLabel ? ` — ${outcome.actionLabel}` : ''}
          </div>
          <div style={{ lineHeight: 1.45 }}>
            {statusResult ? statusResult.message : outcome.message}
          </div>

          {!isVerifiedResolved && (
            <div style={{ marginTop: 6, fontSize: 12, fontWeight: 600 }}>
              Form Locked: Inputs and new submissions remain disabled to prevent duplicate financial entries.
              {!isRecoveryRequired && !isSafeRetry && outcome.nonce
                ? ' Click "Check Transaction Status" first so the system can verify whether the write committed before enabling retry.'
                : ''}
            </div>
          )}

          {isPersistenceDegraded && !isVerifiedResolved && (
            <div
              data-tx-degraded-persistence="true"
              style={{
                marginTop: 8,
                padding: '8px 10px',
                borderRadius: 6,
                background: '#fef2f2',
                border: '1px solid #fca5a5',
                color: '#991b1b',
                fontSize: 12,
                lineHeight: 1.4,
              }}
            >
              <strong>Safety-Degraded Mode (Lock Persistence Failed):</strong>{' '}
              Browser storage could not reliably persist this UNKNOWN transaction lock
              {outcome.persistenceStatus ? ` (${outcome.persistenceStatus})` : ''}. The lock is
              enforced in active memory only and <strong>reload safety is NOT guaranteed</strong>.
              Do NOT reload or close this tab, and do NOT submit a new transaction until status is
              verified below.
              {failureReason ? (
                <div style={{ marginTop: 3, fontFamily: 'monospace', fontSize: 11 }}>
                  Detail: {failureReason}
                </div>
              ) : null}
            </div>
          )}

          {fingerprintMismatchError && (
            <div
              data-tx-payload-mismatch="true"
              style={{
                marginTop: 8,
                padding: '8px 10px',
                borderRadius: 6,
                background: '#fef2f2',
                border: '1px solid #f87171',
                color: '#991b1b',
                fontSize: 12,
                fontWeight: 600,
              }}
            >
              Payload Identity Mismatch Blocked: {fingerprintMismatchError}
            </div>
          )}

          <div style={{ marginTop: 6, fontSize: 11, fontFamily: 'monospace', opacity: 0.9 }}>
            Preserved Nonce: <strong>{outcome.nonce || 'UNAVAILABLE (DEGRADED LOCK)'}</strong>
            {effectiveFingerprint ? (
              <>
                {' '}
                | Payload Fingerprint:{' '}
                <strong title={effectiveFingerprint}>
                  {effectiveFingerprint.length > 23
                    ? `${effectiveFingerprint.slice(0, 23)}…`
                    : effectiveFingerprint}
                </strong>
              </>
            ) : null}
            {outcome.transactionId ? (
              <>
                {' '}
                | Tx ID: <strong>{outcome.transactionId}</strong>
              </>
            ) : null}
            {outcome.correlationId ? (
              <>
                {' '}
                | Correlation ID: <strong>{outcome.correlationId}</strong>
              </>
            ) : null}
            {statusResult?.allocated_id ? (
              <>
                {' '}
                | Allocated ID: <strong>{statusResult.allocated_id}</strong>
              </>
            ) : null}
            {statusResult?.tab_name ? (
              <>
                {' '}
                | Sheet: <strong>{statusResult.tab_name}</strong>
              </>
            ) : null}
            {statusResult?.recovery_decision ? (
              <>
                {' '}
                | Decision: <strong>{statusResult.recovery_decision}</strong>
              </>
            ) : null}
          </div>
          {checkError && (
            <div style={{ marginTop: 6, color: '#b91c1c', fontWeight: 600 }}>
              Status check failed: {checkError}
            </div>
          )}
        </div>
      </div>

      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8, marginTop: 10 }}>
        {outcome.nonce && !isVerifiedResolved && (
          <button
            type="button"
            onClick={handleCheckStatus}
            disabled={checking || cooldownActive}
            data-tx-action="check-status"
            style={{
              padding: '6px 12px',
              borderRadius: 6,
              border: `1px solid ${isRecoveryRequired ? '#dc2626' : '#d97706'}`,
              background: '#ffffff',
              color: isRecoveryRequired ? '#991b1b' : '#92400e',
              fontWeight: 600,
              fontSize: 12,
              cursor: checking || cooldownActive ? 'wait' : 'pointer',
              opacity: cooldownActive && !checking ? 0.7 : 1,
            }}
          >
            {checking
              ? 'Checking Transaction Status…'
              : cooldownActive
              ? 'Please Wait…'
              : 'Check Transaction Status'}
          </button>
        )}

        {onRetry && !isVerifiedResolved && !isRecoveryRequired && outcome.nonce && (
          <button
            type="button"
            onClick={isSafeRetry ? onRetry : undefined}
            disabled={!isSafeRetry}
            data-tx-action="retry-same-nonce"
            title={
              isSafeRetry
                ? 'Verified safe to retry with the same preserved nonce and matching payload fingerprint'
                : hasPayloadMismatch
                ? 'Payload fingerprint mismatch detected; retry blocked'
                : 'Check transaction status first to confirm this write was not already recorded'
            }
            style={{
              padding: '6px 12px',
              borderRadius: 6,
              border: 'none',
              background: isSafeRetry ? '#166534' : '#9ca3af',
              color: '#ffffff',
              fontWeight: 600,
              fontSize: 12,
              cursor: isSafeRetry ? 'pointer' : 'not-allowed',
              opacity: isSafeRetry ? 1 : 0.75,
            }}
          >
            {isSafeRetry ? 'Retry Safely (Same Nonce)' : 'Verify Status Before Retrying'}
          </button>
        )}

        {isVerifiedResolved && onDismiss && (
          <button
            type="button"
            onClick={onDismiss}
            data-tx-action="unlock-verified"
            style={{
              padding: '6px 12px',
              borderRadius: 6,
              border: 'none',
              background: '#059669',
              color: '#ffffff',
              fontWeight: 600,
              fontSize: 12,
              cursor: 'pointer',
            }}
          >
            Unlock Form (Verified)
          </button>
        )}
      </div>
    </div>
  );
};
