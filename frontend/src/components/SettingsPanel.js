import React, { useState, useEffect } from 'react';
import { getPolymarketStatus, derivePolymarketCredentials, getPolymarketBalance } from '../services/api';

function SettingsPanel({ settings, tradingMode, onModeChange, onNotify }) {
  const [switching, setSwitching] = useState(false);
  const [confirmLive, setConfirmLive] = useState(false);
  const [polyStatus, setPolyStatus] = useState(null);
  const [polyBalance, setPolyBalance] = useState(null);
  const [generating, setGenerating] = useState(false);
  const [generatedCreds, setGeneratedCreds] = useState(null);

  useEffect(() => {
    getPolymarketStatus().then(r => setPolyStatus(r.data)).catch(() => {});
    getPolymarketBalance().then(r => setPolyBalance(r.data)).catch(() => {});
  }, []);

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
      const msg = err?.response?.data?.detail || 'Failed to switch trading mode';
      if (onNotify) onNotify(msg, 'error');
      else alert(msg);
    }
    setSwitching(false);
  };

  const handleGenerateKeys = async () => {
    setGenerating(true);
    try {
      const resp = await derivePolymarketCredentials();
      setGeneratedCreds(resp.data.credentials);
      if (onNotify) onNotify('API credentials generated! Restart backend to persist.', 'success');
      // Refresh status
      getPolymarketStatus().then(r => setPolyStatus(r.data)).catch(() => {});
    } catch (err) {
      const msg = err?.response?.data?.detail || 'Failed to generate credentials';
      if (onNotify) onNotify(msg, 'error');
      else alert(msg);
    }
    setGenerating(false);
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
  const liveReady = polyStatus?.live_ready || settings.polymarket_live_ready;

  const items = [
    { label: 'Trading Interval', value: `${settings.interval_seconds}s (${(settings.interval_seconds / 60).toFixed(0)} min)` },
    { label: 'Max Position Size', value: `$${settings.max_position_size}` },
    { label: 'Risk Per Trade', value: `${(settings.risk_per_trade * 100).toFixed(1)}%` },
    { label: 'Stop Loss', value: `${(settings.stop_loss_pct * 100).toFixed(1)}%` },
    { label: 'Take Profit', value: `${(settings.take_profit_pct * 100).toFixed(1)}%` },
    { label: 'X Sentiment', value: settings.has_x_token ? 'Connected' : 'Disabled', status: settings.has_x_token },
  ];

  return (
    <div className="card">
      <div className="card-header">
        <span className="card-title">Configuration</span>
      </div>

      {/* Polymarket API Status */}
      <div style={{
        padding: '1rem',
        marginBottom: '1rem',
        background: liveReady
          ? 'rgba(34, 197, 94, 0.1)'
          : polyStatus?.has_private_key || settings.has_private_key
            ? 'rgba(234, 179, 8, 0.1)'
            : 'rgba(239, 68, 68, 0.1)',
        border: `1px solid ${liveReady
          ? 'rgba(34, 197, 94, 0.3)'
          : polyStatus?.has_private_key || settings.has_private_key
            ? 'rgba(234, 179, 8, 0.3)'
            : 'rgba(239, 68, 68, 0.3)'}`,
        borderRadius: '10px',
      }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '0.5rem' }}>
          <div>
            <div style={{ fontSize: '0.75rem', color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.05em' }}>
              Polymarket API
            </div>
            <div style={{
              fontSize: '1.1rem',
              fontWeight: 700,
              color: liveReady ? 'var(--green)' : 'var(--yellow)',
              marginTop: '0.25rem',
            }}>
              {liveReady ? 'LIVE READY' : settings.has_polymarket_key ? 'API KEY SET' : polyStatus?.has_private_key || settings.has_private_key ? 'PRIVATE KEY SET' : 'NOT CONFIGURED'}
            </div>
          </div>

          {(polyStatus?.has_private_key || settings.has_private_key) && !liveReady && (
            <button
              onClick={handleGenerateKeys}
              disabled={generating}
              style={{
                padding: '0.5rem 1rem',
                borderRadius: '8px',
                border: 'none',
                fontWeight: 600,
                fontSize: '0.8rem',
                cursor: generating ? 'not-allowed' : 'pointer',
                background: 'var(--blue)',
                color: '#fff',
                opacity: generating ? 0.6 : 1,
              }}
            >
              {generating ? 'Generating...' : 'Generate API Keys'}
            </button>
          )}
        </div>

        {/* Status details */}
        <div style={{ fontSize: '0.8rem', color: 'var(--text-muted)' }}>
          {liveReady
            ? 'Connected to Polymarket CLOB. Ready for live trading.'
            : polyStatus?.has_private_key || settings.has_private_key
              ? 'Private key configured. Click "Generate API Keys" to create trading credentials.'
              : 'Set POLYMARKET_PRIVATE_KEY in .env to enable live trading.'}
        </div>

        {settings.polymarket_funder && (
          <div style={{ fontSize: '0.75rem', color: 'var(--text-muted)', marginTop: '0.25rem', fontFamily: 'monospace' }}>
            Wallet: {settings.polymarket_funder.slice(0, 6)}...{settings.polymarket_funder.slice(-4)}
          </div>
        )}

        {polyBalance && polyBalance.balance > 0 && (
          <div style={{ fontSize: '0.85rem', color: 'var(--green)', marginTop: '0.25rem', fontWeight: 600 }}>
            Balance: ${parseFloat(polyBalance.balance).toFixed(2)} USDC
          </div>
        )}

        {/* Generated credentials display */}
        {generatedCreds && (
          <div style={{
            marginTop: '0.75rem',
            padding: '0.75rem',
            background: 'var(--bg-primary)',
            borderRadius: '8px',
            fontSize: '0.75rem',
          }}>
            <div style={{ fontWeight: 700, marginBottom: '0.5rem', color: 'var(--green)' }}>
              Credentials Generated - Add to .env:
            </div>
            {Object.entries(generatedCreds).map(([key, val]) => (
              <div key={key} style={{ fontFamily: 'monospace', color: 'var(--text-secondary)', marginBottom: '0.2rem' }}>
                {key}={val}
              </div>
            ))}
            <div style={{ color: 'var(--yellow)', marginTop: '0.5rem', fontSize: '0.7rem' }}>
              Restart backend after updating .env to persist credentials.
            </div>
          </div>
        )}
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
        Configure settings via <code>.env</code> file. Restart the backend after changes.
      </div>
    </div>
  );
}

export default SettingsPanel;
