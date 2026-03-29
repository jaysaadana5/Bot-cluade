import React from 'react';

function SignalPanel({ signal }) {
  if (!signal) {
    return (
      <div className="card">
        <div className="card-header">
          <span className="card-title">Current Signal</span>
        </div>
        <div className="loading">Waiting for first trading cycle...</div>
      </div>
    );
  }

  const direction = signal.direction || 'HOLD';
  const strength = signal.strength || 0;
  const confidence = signal.confidence || 0;
  const combinedScore = signal.combined_score || 0;

  // Support both old format (signal.technical) and new regime format (signal.spot_ta)
  const spotTa = signal.spot_ta || signal.technical || {};
  const indicators = spotTa.indicators || {};
  const reasons = signal.reasons || spotTa.reasons || [];

  // Scores - support both old and new formats
  const scores = signal.scores || {};

  const dirColor = direction === 'BUY' ? 'var(--green)' : direction === 'SELL' ? 'var(--red)' : 'var(--yellow)';
  const dirBg = direction === 'BUY' ? 'var(--green-bg)' : direction === 'SELL' ? 'var(--red-bg)' : 'var(--yellow-bg)';

  return (
    <div className="card">
      <div className="card-header">
        <span className="card-title">Current Signal</span>
      </div>

      {/* Direction Badge */}
      <div style={{
        display: 'inline-flex',
        alignItems: 'center',
        gap: '0.5rem',
        padding: '0.5rem 1rem',
        background: dirBg,
        color: dirColor,
        borderRadius: '8px',
        fontWeight: 700,
        fontSize: '1.1rem',
        fontFamily: "'JetBrains Mono', monospace",
        marginBottom: '1rem',
      }}>
        {direction === 'BUY' ? '\u2191' : direction === 'SELL' ? '\u2193' : '\u2194'} {direction}
      </div>

      {/* Signal Strength & Confidence */}
      <div style={{ marginBottom: '1rem' }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '0.25rem' }}>
          <span className="stat-label">Confidence</span>
          <span className="mono" style={{ fontSize: '0.85rem', fontWeight: 600 }}>
            {(confidence * 100).toFixed(0)}%
          </span>
        </div>
        <div className="signal-bar">
          <div
            className="signal-fill"
            style={{
              width: `${confidence * 100}%`,
              background: dirColor,
            }}
          />
        </div>
      </div>

      {/* Scores */}
      <div style={{ display: 'flex', gap: '1rem', marginBottom: '1rem', flexWrap: 'wrap' }}>
        {combinedScore !== 0 && (
          <div>
            <div className="stat-label">Combined</div>
            <div className="mono" style={{ fontWeight: 600 }}>{combinedScore.toFixed(3)}</div>
          </div>
        )}
        {scores.spot_ta !== undefined && (
          <div>
            <div className="stat-label">Spot TA</div>
            <div className="mono" style={{ fontWeight: 600 }}>{scores.spot_ta.toFixed(3)}</div>
          </div>
        )}
        {scores.divergence !== undefined && (
          <div>
            <div className="stat-label">Divergence</div>
            <div className="mono" style={{ fontWeight: 600 }}>{scores.divergence.toFixed(3)}</div>
          </div>
        )}
        {scores.sentiment !== undefined && (
          <div>
            <div className="stat-label">Sentiment</div>
            <div className="mono" style={{ fontWeight: 600 }}>{scores.sentiment.toFixed(3)}</div>
          </div>
        )}
        {/* Fallback for old format */}
        {signal.tech_score !== undefined && (
          <div>
            <div className="stat-label">Tech</div>
            <div className="mono" style={{ fontWeight: 600 }}>{signal.tech_score.toFixed(3)}</div>
          </div>
        )}
        {signal.sent_score !== undefined && (
          <div>
            <div className="stat-label">Sent</div>
            <div className="mono" style={{ fontWeight: 600 }}>{signal.sent_score.toFixed(3)}</div>
          </div>
        )}
      </div>

      {/* Regime info if available */}
      {signal.reason && (
        <div style={{
          padding: '0.5rem 0.75rem',
          background: 'var(--bg-primary)',
          borderRadius: '6px',
          fontSize: '0.8rem',
          color: 'var(--text-secondary)',
          marginBottom: '0.75rem',
        }}>
          {signal.reason}
        </div>
      )}

      {/* Indicators */}
      {indicators.rsi != null && (
        <div style={{ marginBottom: '0.5rem' }}>
          <div className="stat-label">Indicators</div>
          <div style={{ display: 'flex', gap: '1rem', marginTop: '0.25rem', fontSize: '0.85rem', flexWrap: 'wrap' }}>
            <span className="mono">RSI: <strong>{indicators.rsi}</strong></span>
            {indicators.macd && (
              <span className="mono">MACD: <strong>{indicators.macd.histogram?.toFixed(4)}</strong></span>
            )}
            {indicators.bollinger_pct_b != null && (
              <span className="mono">BB%: <strong>{(indicators.bollinger_pct_b * 100).toFixed(1)}%</strong></span>
            )}
          </div>
        </div>
      )}

      {/* Reasons */}
      {reasons.length > 0 && (
        <div style={{ marginTop: '0.75rem' }}>
          <div className="stat-label" style={{ marginBottom: '0.25rem' }}>Reasons</div>
          {reasons.slice(0, 8).map((reason, i) => (
            <div key={i} style={{
              fontSize: '0.8rem',
              color: 'var(--text-secondary)',
              padding: '0.2rem 0',
            }}>
              - {reason}
            </div>
          ))}
          {reasons.length > 8 && (
            <div style={{ fontSize: '0.75rem', color: 'var(--text-muted)' }}>
              +{reasons.length - 8} more...
            </div>
          )}
        </div>
      )}
    </div>
  );
}

export default SignalPanel;
