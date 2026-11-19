import React, { useState } from 'react';
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

/**
 * Reusable 504 / PENDING_UNKNOWN recovery banner.
 * Displays "Outcome unknown / checking transaction status", retains the exact client nonce &
 * correlation_id, warns that form inputs are NOT SAVED yet, and enables read-only verification
 * via GET /api/v2/transactions/status/{nonce} before retrying safely with the SAME nonce.
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

  if (!outcome) return null;

  const handleCheckStatus = async () => {
    if (!outcome.nonce || checking) return;
    setChecking(true);
    setCheckError(null);
    try {
      const res = await checkV2TransactionStatus(outcome.nonce, outcome.correlationId);
      setStatusResult(res);
      if (res.status === 'CONFIRMED_RECORDED' && onConfirmedRecorded) {
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
    }
  };

  const isConfirmed = statusResult?.status === 'CONFIRMED_RECORDED';
  const isSafeRetry = statusResult?.status === 'NOT_FOUND_SAFE_TO_RETRY_SAME_NONCE';

  return (
    <div
      role="alert"
      style={{
        background: isConfirmed ? '#ecfdf5' : '#fffbeb',
        border: `1px solid ${isConfirmed ? '#6ee7b7' : '#f59e0b'}`,
        borderRadius: 10,
        padding: '12px 14px',
        marginBottom: 14,
        color: isConfirmed ? '#065f46' : '#92400e',
        fontSize: 13,
      }}
    >
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: 10 }}>
        <div>
          <div style={{ fontWeight: 700, marginBottom: 4 }}>
            {isConfirmed
              ? 'Transaction Confirmed Recorded in Google Sheets'
              : 'Outcome unknown / checking transaction status (NOT SAVED CONFIRMED)'}
            {outcome.actionLabel ? ` — ${outcome.actionLabel}` : ''}
          </div>
          <div style={{ lineHeight: 1.45 }}>
            {statusResult ? statusResult.message : outcome.message}
          </div>
          <div style={{ marginTop: 6, fontSize: 11, fontFamily: 'monospace', opacity: 0.9 }}>
            Preserved Nonce: <strong>{outcome.nonce || 'N/A'}</strong>
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
            disabled={checking}
            style={{
              padding: '6px 12px',
              borderRadius: 6,
              border: '1px solid #d97706',
              background: '#ffffff',
              color: '#92400e',
              fontWeight: 600,
              fontSize: 12,
              cursor: checking ? 'wait' : 'pointer',
            }}
          >
            {checking ? 'Checking Transaction Status…' : 'Check Transaction Status'}
          </button>
        )}

        {onRetry && !isConfirmed && (
          <button
            type="button"
            onClick={onRetry}
            style={{
              padding: '6px 12px',
              borderRadius: 6,
              border: 'none',
              background: isSafeRetry ? '#166534' : '#b45309',
              color: '#ffffff',
              fontWeight: 600,
              fontSize: 12,
              cursor: 'pointer',
            }}
          >
            Retry Safely (Same Nonce)
          </button>
        )}
      </div>
    </div>
  );
};
