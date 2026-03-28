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
  const tech = signal.technical || {};
  const indicators = tech.indicators || {};

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

      {/* Signal Strength */}
      <div style={{ marginBottom: '1rem' }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '0.25rem' }}>
          <span className="stat-label">Signal Strength</span>
          <span className="mono" style={{ fontSize: '0.85rem', fontWeight: 600 }}>
            {(strength * 100).toFixed(0)}%
          </span>
        </div>
        <div className="signal-bar">
          <div
            className="signal-fill"
            style={{
              width: `${strength * 100}%`,
              background: dirColor,
            }}
          />
        </div>
      </div>

      {/* Scores */}
      <div style={{ display: 'flex', gap: '1rem', marginBottom: '1rem' }}>
        <div>
          <div className="stat-label">Tech Score</div>
          <div className="mono" style={{ fontWeight: 600 }}>{signal.tech_score?.toFixed(3)}</div>
        </div>
        <div>
          <div className="stat-label">Sent Score</div>
          <div className="mono" style={{ fontWeight: 600 }}>{signal.sent_score?.toFixed(3)}</div>
        </div>
        <div>
          <div className="stat-label">Combined</div>
          <div className="mono" style={{ fontWeight: 600 }}>{signal.combined_score?.toFixed(3)}</div>
        </div>
      </div>

      {/* Indicators */}
      {indicators.rsi != null && (
        <div style={{ marginBottom: '0.5rem' }}>
          <div className="stat-label">Indicators</div>
          <div style={{ display: 'flex', gap: '1rem', marginTop: '0.25rem', fontSize: '0.85rem' }}>
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
      {tech.reasons?.length > 0 && (
        <div style={{ marginTop: '0.75rem' }}>
          <div className="stat-label" style={{ marginBottom: '0.25rem' }}>Reasons</div>
          {tech.reasons.map((reason, i) => (
            <div key={i} style={{
              fontSize: '0.8rem',
              color: 'var(--text-secondary)',
              padding: '0.2rem 0',
            }}>
              - {reason}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

export default SignalPanel;
