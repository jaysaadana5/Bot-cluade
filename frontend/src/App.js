import React, { useState, useCallback } from 'react';
import { usePolling } from './hooks/usePolling';
import * as api from './services/api';

import TradingViewChart from './components/TradingViewChart';
import StatsCards from './components/StatsCards';
import TradesTable from './components/TradesTable';
import SentimentPanel from './components/SentimentPanel';
import SignalPanel from './components/SignalPanel';
import MarketsList from './components/MarketsList';
import PnLChart from './components/PnLChart';
import SettingsPanel from './components/SettingsPanel';

function App() {
  const [activeTab, setActiveTab] = useState('dashboard');
  const [actionLoading, setActionLoading] = useState(false);
  const [notification, setNotification] = useState(null);

  const showNotification = (message, type = 'info') => {
    setNotification({ message, type });
    setTimeout(() => setNotification(null), 5000);
  };

  // Polling hooks
  const { data: botStatus, error: statusError, refetch: refetchStatus } = usePolling(api.getBotStatus, 5000);
  const { data: portfolio, refetch: refetchPortfolio } = usePolling(api.getPortfolio, 10000);
  const { data: sentiment } = usePolling(api.getSentiment, 30000);
  const { data: sentimentHistory } = usePolling(api.getSentimentHistory, 30000);
  const { data: tradesData } = usePolling(api.getTrades, 10000);
  const { data: marketsData } = usePolling(
    api.getMarkets,
    60000,
    activeTab === 'markets',
  );
  const { data: settingsData } = usePolling(
    api.getSettings,
    60000,
  );

  const handleStart = useCallback(async () => {
    setActionLoading(true);
    try {
      const res = await api.startBot();
      showNotification(res.data?.message || 'Bot started!', 'success');
      await refetchStatus();
    } catch (err) {
      const msg = err.response?.data?.detail || err.message || 'Failed to start bot';
      showNotification(`Error: ${msg}`, 'error');
      console.error('Failed to start bot:', err);
    }
    setActionLoading(false);
  }, [refetchStatus]);

  const handleStop = useCallback(async () => {
    setActionLoading(true);
    try {
      const res = await api.stopBot();
      showNotification(res.data?.message || 'Bot stopped', 'info');
      await refetchStatus();
    } catch (err) {
      const msg = err.response?.data?.detail || err.message || 'Failed to stop bot';
      showNotification(`Error: ${msg}`, 'error');
      console.error('Failed to stop bot:', err);
    }
    setActionLoading(false);
  }, [refetchStatus]);

  const handleRunOnce = useCallback(async () => {
    setActionLoading(true);
    try {
      const res = await api.runBotOnce();
      const result = res.data;
      const status = result?.status || 'done';
      const trade = result?.trade;
      if (trade) {
        showNotification(`Trade: ${trade.side} ${trade.size}@${trade.price} (${trade.mode})`, 'success');
      } else {
        showNotification(`Cycle complete: ${status}`, 'info');
      }
      await Promise.all([refetchStatus(), refetchPortfolio()]);
    } catch (err) {
      const msg = err.response?.data?.detail || err.message || 'Failed to run cycle';
      showNotification(`Error: ${msg}`, 'error');
      console.error('Failed to run cycle:', err);
    }
    setActionLoading(false);
  }, [refetchStatus, refetchPortfolio]);

  const handleModeChange = useCallback(async (mode) => {
    try {
      const res = await api.setTradingMode(mode);
      showNotification(res.data?.message || `Switched to ${mode}`, 'success');
      await refetchStatus();
    } catch (err) {
      const msg = err.response?.data?.detail || err.message || 'Failed to switch mode';
      showNotification(`Error: ${msg}`, 'error');
      throw err;
    }
  }, [refetchStatus]);

  const isRunning = botStatus?.is_running || false;
  const tradingMode = botStatus?.trading_mode || settingsData?.trading_mode || 'paper';
  const backendConnected = !statusError;

  const tabs = [
    { id: 'dashboard', label: 'Dashboard' },
    { id: 'chart', label: 'Chart' },
    { id: 'markets', label: 'Markets' },
    { id: 'settings', label: 'Settings' },
  ];

  return (
    <div className="app">
      {/* Notification Banner */}
      {notification && (
        <div style={{
          position: 'fixed',
          top: '1rem',
          right: '1rem',
          zIndex: 9999,
          padding: '0.75rem 1.25rem',
          borderRadius: '10px',
          fontSize: '0.85rem',
          fontWeight: 600,
          maxWidth: '400px',
          animation: 'fadeIn 0.3s ease',
          background: notification.type === 'success' ? 'rgba(34, 197, 94, 0.15)' :
                      notification.type === 'error' ? 'rgba(239, 68, 68, 0.15)' :
                      'rgba(59, 130, 246, 0.15)',
          color: notification.type === 'success' ? '#22c55e' :
                 notification.type === 'error' ? '#ef4444' :
                 '#3b82f6',
          border: `1px solid ${
            notification.type === 'success' ? 'rgba(34, 197, 94, 0.3)' :
            notification.type === 'error' ? 'rgba(239, 68, 68, 0.3)' :
            'rgba(59, 130, 246, 0.3)'
          }`,
          backdropFilter: 'blur(10px)',
        }}>
          {notification.message}
        </div>
      )}

      {/* Backend Disconnected Warning */}
      {!backendConnected && (
        <div style={{
          background: 'rgba(239, 68, 68, 0.15)',
          color: '#ef4444',
          textAlign: 'center',
          padding: '0.5rem',
          fontSize: '0.85rem',
          fontWeight: 600,
        }}>
          Backend not reachable - make sure the backend is running on port 8000
        </div>
      )}

      {/* Header */}
      <header className="header">
        <div className="header-left">
          <h1>Polymarket BTC Bot</h1>
          <div className="nav-tabs">
            {tabs.map((tab) => (
              <button
                key={tab.id}
                className={`nav-tab ${activeTab === tab.id ? 'active' : ''}`}
                onClick={() => setActiveTab(tab.id)}
              >
                {tab.label}
              </button>
            ))}
          </div>
        </div>
        <div className="header-right">
          <div style={{
            padding: '0.25rem 0.75rem',
            borderRadius: '6px',
            fontSize: '0.75rem',
            fontWeight: 700,
            letterSpacing: '0.05em',
            background: tradingMode === 'paper' ? 'rgba(234, 179, 8, 0.15)' : 'rgba(239, 68, 68, 0.15)',
            color: tradingMode === 'paper' ? '#eab308' : '#ef4444',
            border: `1px solid ${tradingMode === 'paper' ? 'rgba(234, 179, 8, 0.3)' : 'rgba(239, 68, 68, 0.3)'}`,
          }}>
            {tradingMode === 'paper' ? 'PAPER' : 'LIVE'}
          </div>
          <div className={`status-badge ${isRunning ? 'running' : 'stopped'}`}>
            <div className={`status-dot ${isRunning ? 'running' : 'stopped'}`} />
            {isRunning ? 'Running' : 'Stopped'}
          </div>
          {!isRunning ? (
            <button className="btn btn-success" onClick={handleStart} disabled={actionLoading || !backendConnected}>
              {actionLoading ? 'Starting...' : 'Start Bot'}
            </button>
          ) : (
            <button className="btn btn-danger" onClick={handleStop} disabled={actionLoading}>
              {actionLoading ? 'Stopping...' : 'Stop Bot'}
            </button>
          )}
          <button className="btn btn-outline" onClick={handleRunOnce} disabled={actionLoading || !backendConnected}>
            {actionLoading ? 'Running...' : 'Run Once'}
          </button>
        </div>
      </header>

      {/* Main Content */}
      <main className="main">
        {activeTab === 'dashboard' && (
          <div style={{ display: 'flex', flexDirection: 'column', gap: '1.25rem' }}>
            <StatsCards portfolio={portfolio} botStatus={botStatus} sentiment={sentiment} />

            <div className="grid grid-2">
              <PnLChart trades={tradesData?.trades || []} />
              <SignalPanel signal={botStatus?.last_signal} />
            </div>

            <div className="grid grid-2">
              <SentimentPanel sentiment={sentiment} history={sentimentHistory?.history || []} />
              <SettingsPanel settings={settingsData} tradingMode={tradingMode} onModeChange={handleModeChange} onNotify={showNotification} />
            </div>

            <TradesTable trades={tradesData?.trades || []} />
          </div>
        )}

        {activeTab === 'chart' && (
          <div style={{ display: 'flex', flexDirection: 'column', gap: '1.25rem' }}>
            <TradingViewChart symbol="BTCUSD" height={600} />
            <div className="grid grid-2">
              <SignalPanel signal={botStatus?.last_signal} />
              <SentimentPanel sentiment={sentiment} history={sentimentHistory?.history || []} />
            </div>
          </div>
        )}

        {activeTab === 'markets' && (
          <div style={{ display: 'flex', flexDirection: 'column', gap: '1.25rem' }}>
            <MarketsList markets={marketsData?.markets || []} />
          </div>
        )}

        {activeTab === 'settings' && (
          <div style={{ display: 'flex', flexDirection: 'column', gap: '1.25rem' }}>
            <div className="grid grid-2">
              <SettingsPanel settings={settingsData} tradingMode={tradingMode} onModeChange={handleModeChange} onNotify={showNotification} />
              <div className="card">
                <div className="card-header">
                  <span className="card-title">Bot Status</span>
                </div>
                <pre style={{
                  background: 'var(--bg-primary)',
                  padding: '1rem',
                  borderRadius: '8px',
                  fontSize: '0.8rem',
                  overflow: 'auto',
                  maxHeight: '400px',
                  color: 'var(--text-secondary)',
                }}>
                  {JSON.stringify(botStatus, null, 2)}
                </pre>
              </div>
            </div>
          </div>
        )}
      </main>
    </div>
  );
}

export default App;
