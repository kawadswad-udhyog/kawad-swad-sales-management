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
}

const STATUS_CHECK_COOLDOWN_MS = 2000;

/**
 * Reusable 504 / PENDING_UNKNOWN / RECOVERY_REQUIRED transaction safety banner.
 * - Retains exact client nonce & correlation_id without clearing user inputs.
 * - Blocks retrying until GET /api/v2/transactions/status/{nonce} confirms
 *   `NOT_FOUND_SAFE_TO_RETRY_SAME_NONCE` (`safe_to_retry_same_nonce === true`).
 * - Permanently disables automatic retry for `CONFIRMED_RECORDED`, `RECONCILED`,
 *   and `RECOVERY_REQUIRED` (quarantined partial/duplicate effects).
 */
export const UnknownOutcomeBanner: React.FC<UnknownOutcomeBannerProps> = ({
  outcome,
  onRetry,
  onConfirmedRecorded,
  onDismiss,
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
          : 'Could not reach transaction status endpoint. Keep your form inputs and try checking again.'
      );
    } finally {
      setChecking(false);
      setCooldownActive(true);
      setTimeout(() => setCooldownActive(false), STATUS_CHECK_COOLDOWN_MS);
    }
  };

  const isConfirmed =
    statusResult?.status === 'CONFIRMED_RECORDED' || statusResult?.status === 'RECONCILED';
  const isRecoveryRequired =
    Boolean(outcome.recoveryRequired) || statusResult?.status === 'RECOVERY_REQUIRED';
  const isInProgress = statusResult?.status === 'IN_PROGRESS';
  const isSafeRetry =
    !isRecoveryRequired &&
    statusResult?.status === 'NOT_FOUND_SAFE_TO_RETRY_SAME_NONCE' &&
    statusResult?.safe_to_retry_same_nonce === true;

  const palette = isConfirmed
    ? { bg: '#ecfdf5', border: '#6ee7b7', text: '#065f46' }
    : isRecoveryRequired
    ? { bg: '#fef2f2', border: '#f87171', text: '#991b1b' }
    : { bg: '#fffbeb', border: '#f59e0b', text: '#92400e' };

  const heading = isConfirmed
    ? statusResult?.status === 'RECONCILED'
      ? 'Transaction Reconciled by Administrator'
      : 'Transaction Confirmed Recorded in Google Sheets'
    : isRecoveryRequired
    ? 'Recovery Required — Automatic Retry Disabled'
    : isInProgress
    ? 'Transaction Still Processing on Server'
    : isSafeRetry
    ? 'Verified Not Recorded — Safe to Retry with Same Nonce'
    : 'Outcome Unknown — Check Transaction Status Before Retrying';

  return (
    <div
      role="alert"
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
          {!isConfirmed && !isRecoveryRequired && !isSafeRetry && (
            <div style={{ marginTop: 4, fontSize: 12, opacity: 0.9 }}>
              Click &ldquo;Check Transaction Status&rdquo; first so the system can verify whether the write committed before enabling retry.
            </div>
          )}
          <div style={{ marginTop: 6, fontSize: 11, fontFamily: 'monospace', opacity: 0.9 }}>
            Preserved Nonce: <strong>{outcome.nonce || 'N/A'}</strong>
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
          </div>
          {checkError && (
            <div style={{ marginTop: 6, color: '#b91c1c', fontWeight: 600 }}>
              Status check failed: {checkError}
            </div>
          )}
        </div>
        {onDismiss && (
          <button
            type="button"
            onClick={onDismiss}
            style={{
              background: 'transparent',
              border: 'none',
              color: 'inherit',
              cursor: 'pointer',
              fontWeight: 700,
              fontSize: 14,
              padding: '2px 6px',
            }}
            aria-label="Dismiss status banner"
          >
            ✕
          </button>
        )}
      </div>

      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8, marginTop: 10 }}>
        {outcome.nonce && !isConfirmed && (
          <button
            type="button"
            onClick={handleCheckStatus}
            disabled={checking || cooldownActive}
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

        {onRetry && !isConfirmed && !isRecoveryRequired && (
          <button
            type="button"
            onClick={isSafeRetry ? onRetry : undefined}
            disabled={!isSafeRetry}
            title={
              isSafeRetry
                ? 'Verified safe to retry with the same preserved nonce'
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
      </div>
    </div>
  );
};
