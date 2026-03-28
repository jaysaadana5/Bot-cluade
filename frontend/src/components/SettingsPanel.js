import React, { useState } from 'react';

function SettingsPanel({ settings, tradingMode, onModeChange }) {
  const [switching, setSwitching] = useState(false);
  const [confirmLive, setConfirmLive] = useState(false);

  const handleModeToggle = async () => {
    const newMode = tradingMode === 'paper' ? 'live' : 'paper';

    if (newMode === 'live' && !confirmLive) {
      setConfirmLive(true);
      return;
    }

    setSwitching(true);
    setConfirmLive(false);
    try {
      if (onModeChange) {
        await onModeChange(newMode);
      }
    } catch (err) {
      console.error('Failed to switch mode:', err);
      alert(err?.response?.data?.detail || 'Failed to switch trading mode');
    }
    setSwitching(false);
  };

  const cancelLiveSwitch = () => setConfirmLive(false);

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

  const isPaper = tradingMode === 'paper';

  const items = [
    { label: 'Trading Interval', value: `${settings.interval_seconds}s (${(settings.interval_seconds / 60).toFixed(0)} min)` },
    { label: 'Max Position Size', value: `$${settings.max_position_size}` },
    { label: 'Risk Per Trade', value: `${(settings.risk_per_trade * 100).toFixed(1)}%` },
    { label: 'Stop Loss', value: `${(settings.stop_loss_pct * 100).toFixed(1)}%` },
    { label: 'Take Profit', value: `${(settings.take_profit_pct * 100).toFixed(1)}%` },
    { label: 'Polymarket API', value: settings.has_polymarket_key ? 'Connected' : 'Not Set', status: settings.has_polymarket_key },
    { label: 'X Sentiment', value: settings.has_x_token ? 'Connected' : 'Disabled', status: settings.has_x_token },
  ];

  return (
    <div className="card">
      <div className="card-header">
        <span className="card-title">Configuration</span>
      </div>

      {/* Trading Mode Toggle */}
      <div style={{
        padding: '1rem',
        marginBottom: '1rem',
        background: isPaper ? 'rgba(234, 179, 8, 0.1)' : 'rgba(239, 68, 68, 0.1)',
        border: `1px solid ${isPaper ? 'rgba(234, 179, 8, 0.3)' : 'rgba(239, 68, 68, 0.3)'}`,
        borderRadius: '10px',
      }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '0.5rem' }}>
          <div>
            <div style={{ fontSize: '0.75rem', color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.05em' }}>
              Trading Mode
            </div>
            <div style={{
              fontSize: '1.2rem',
              fontWeight: 700,
              color: isPaper ? 'var(--yellow)' : 'var(--red)',
              marginTop: '0.25rem',
            }}>
              {isPaper ? 'PAPER TRADING' : 'LIVE TRADING'}
            </div>
          </div>

          <button
            onClick={handleModeToggle}
            disabled={switching}
            style={{
              padding: '0.5rem 1.25rem',
              borderRadius: '8px',
              border: 'none',
              fontWeight: 600,
              fontSize: '0.85rem',
              cursor: switching ? 'not-allowed' : 'pointer',
              background: isPaper ? 'var(--red)' : 'var(--yellow)',
              color: '#fff',
              opacity: switching ? 0.6 : 1,
              transition: 'all 0.2s',
            }}
          >
            {switching ? 'Switching...' : isPaper ? 'Switch to LIVE' : 'Switch to PAPER'}
          </button>
        </div>

        <div style={{ fontSize: '0.8rem', color: 'var(--text-muted)' }}>
          {isPaper
            ? 'Simulated trading with virtual funds. No real money at risk.'
            : 'Real orders placed on Polymarket. Real money at risk!'}
        </div>

        {settings.paper_starting_balance && isPaper && (
          <div style={{ fontSize: '0.8rem', color: 'var(--text-secondary)', marginTop: '0.25rem' }}>
            Paper Balance: ${settings.paper_starting_balance.toLocaleString()}
          </div>
        )}
      </div>

      {/* Live Mode Confirmation Dialog */}
      {confirmLive && (
        <div style={{
          padding: '1rem',
          marginBottom: '1rem',
          background: 'rgba(239, 68, 68, 0.15)',
          border: '1px solid rgba(239, 68, 68, 0.5)',
          borderRadius: '10px',
        }}>
          <div style={{ fontWeight: 700, color: 'var(--red)', marginBottom: '0.5rem' }}>
            Confirm Live Trading
          </div>
          <div style={{ fontSize: '0.85rem', color: 'var(--text-secondary)', marginBottom: '0.75rem' }}>
            This will place REAL orders on Polymarket using your configured API keys.
            Make sure your Polymarket API is properly configured and funded.
          </div>
          <div style={{ display: 'flex', gap: '0.5rem' }}>
            <button
              onClick={handleModeToggle}
              style={{
                padding: '0.4rem 1rem',
                borderRadius: '6px',
                border: 'none',
                fontWeight: 600,
                fontSize: '0.8rem',
                cursor: 'pointer',
                background: 'var(--red)',
                color: '#fff',
              }}
            >
              Yes, Go Live
            </button>
            <button
              onClick={cancelLiveSwitch}
              style={{
                padding: '0.4rem 1rem',
                borderRadius: '6px',
                border: '1px solid var(--text-muted)',
                fontWeight: 600,
                fontSize: '0.8rem',
                cursor: 'pointer',
                background: 'transparent',
                color: 'var(--text-secondary)',
              }}
            >
              Cancel
            </button>
          </div>
        </div>
      )}

      {/* Settings List */}
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
