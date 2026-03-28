import React from 'react';

function SettingsPanel({ settings }) {
  if (!settings) {
    return (
      <div className="card">
        <div className="card-header">
          <span className="card-title">Configuration</span>
        </div>
        <div className="loading">Loading settings...</div>
      </div>
    );
  }

  const items = [
    { label: 'Trading Interval', value: `${settings.interval_seconds}s (${(settings.interval_seconds / 60).toFixed(0)} min)` },
    { label: 'Max Position Size', value: `$${settings.max_position_size}` },
    { label: 'Risk Per Trade', value: `${(settings.risk_per_trade * 100).toFixed(1)}%` },
    { label: 'Stop Loss', value: `${(settings.stop_loss_pct * 100).toFixed(1)}%` },
    { label: 'Take Profit', value: `${(settings.take_profit_pct * 100).toFixed(1)}%` },
    { label: 'Polymarket API', value: settings.has_polymarket_key ? 'Connected' : 'Paper Trading', status: settings.has_polymarket_key },
    { label: 'X Sentiment', value: settings.has_x_token ? 'Connected' : 'Disabled', status: settings.has_x_token },
  ];

  return (
    <div className="card">
      <div className="card-header">
        <span className="card-title">Configuration</span>
      </div>
      <div>
        {items.map((item, i) => (
          <div key={i} style={{
            display: 'flex',
            justifyContent: 'space-between',
            alignItems: 'center',
            padding: '0.6rem 0',
            borderBottom: i < items.length - 1 ? '1px solid rgba(51, 65, 85, 0.5)' : 'none',
          }}>
            <span style={{ color: 'var(--text-secondary)', fontSize: '0.85rem' }}>{item.label}</span>
            <span className="mono" style={{
              fontWeight: 600,
              fontSize: '0.85rem',
              color: item.status !== undefined ? (item.status ? 'var(--green)' : 'var(--yellow)') : 'var(--text-primary)',
            }}>
              {item.value}
            </span>
          </div>
        ))}
      </div>
      <div style={{ marginTop: '1rem', padding: '0.75rem', background: 'var(--bg-primary)', borderRadius: '8px', fontSize: '0.8rem', color: 'var(--text-muted)' }}>
        Configure settings via <code>.env</code> file on your VPS. Restart the backend after changes.
      </div>
    </div>
  );
}

export default SettingsPanel;
