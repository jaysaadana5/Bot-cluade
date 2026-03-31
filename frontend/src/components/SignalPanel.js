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
        <span className="card-title">CURRENT SIGNAL</span>
        <span style={{ fontSize: '0.75rem', color: 'var(--text-muted)' }}>BTC 5min</span>
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
        {direction === 'BUY' ? '\u2191 BTC UP' : direction === 'SELL' ? '\u2193 BTC DOWN' : '\u2194 HOLD'}
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

      {/* Polymarket Odds */}
      {signal.polymarket && (
        <div style={{
          padding: '0.75rem',
          background: 'var(--bg-primary)',
          borderRadius: '8px',
          marginBottom: '1rem',
        }}>
          <div className="stat-label" style={{ marginBottom: '0.5rem' }}>Polymarket Odds</div>
          <div style={{ display: 'flex', gap: '1.5rem', flexWrap: 'wrap', fontSize: '0.9rem' }}>
            <div>
              <span style={{ color: 'var(--text-muted)' }}>YES (UP): </span>
              <span className="mono" style={{ fontWeight: 700, color: 'var(--green)' }}>
                {(signal.polymarket.yes_price * 100).toFixed(1)}%
              </span>
            </div>
            <div>
              <span style={{ color: 'var(--text-muted)' }}>NO (DOWN): </span>
              <span className="mono" style={{ fontWeight: 700, color: 'var(--red)' }}>
                {(signal.polymarket.no_price * 100).toFixed(1)}%
              </span>
            </div>
            {signal.polymarket.buy_pressure != null && (
              <div>
                <span style={{ color: 'var(--text-muted)' }}>Buy Pressure: </span>
                <span className="mono" style={{ fontWeight: 600 }}>
                  {(signal.polymarket.buy_pressure * 100).toFixed(0)}%
                </span>
              </div>
            )}
          </div>
          {signal.polymarket.market && (
            <div style={{ marginTop: '0.5rem', fontSize: '0.75rem', color: 'var(--text-muted)' }}>
              Market: {signal.polymarket.market}
            </div>
          )}
        </div>
      )}

      {/* Scores */}
      <div style={{ display: 'flex', gap: '1rem', marginBottom: '1rem', flexWrap: 'wrap' }}>
        {scores.polymarket_yes !== undefined && (
          <div>
            <div className="stat-label">YES Price</div>
            <div className="mono" style={{ fontWeight: 600, color: 'var(--green)' }}>{(scores.polymarket_yes * 100).toFixed(1)}%</div>
          </div>
        )}
        {scores.polymarket_no !== undefined && (
          <div>
            <div className="stat-label">NO Price</div>
            <div className="mono" style={{ fontWeight: 600, color: 'var(--red)' }}>{(scores.polymarket_no * 100).toFixed(1)}%</div>
          </div>
        )}
        {scores.spread !== undefined && scores.spread > 0 && (
          <div>
            <div className="stat-label">Spread</div>
            <div className="mono" style={{ fontWeight: 600 }}>{(scores.spread * 100).toFixed(2)}%</div>
          </div>
        )}
        {scores.buy_pressure !== undefined && (
          <div>
            <div className="stat-label">Book Pressure</div>
            <div className="mono" style={{ fontWeight: 600 }}>{(scores.buy_pressure * 100).toFixed(0)}%</div>
          </div>
        )}
      </div>

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
