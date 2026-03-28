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

  // Polling hooks
  const { data: botStatus, refetch: refetchStatus } = usePolling(api.getBotStatus, 5000);
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
    activeTab === 'settings',
  );

  const handleStart = useCallback(async () => {
    setActionLoading(true);
    try {
      await api.startBot();
      await refetchStatus();
    } catch (err) {
      console.error('Failed to start bot:', err);
    }
    setActionLoading(false);
  }, [refetchStatus]);

  const handleStop = useCallback(async () => {
    setActionLoading(true);
    try {
      await api.stopBot();
      await refetchStatus();
    } catch (err) {
      console.error('Failed to stop bot:', err);
    }
    setActionLoading(false);
  }, [refetchStatus]);

  const handleRunOnce = useCallback(async () => {
    setActionLoading(true);
    try {
      await api.runBotOnce();
      await Promise.all([refetchStatus(), refetchPortfolio()]);
    } catch (err) {
      console.error('Failed to run cycle:', err);
    }
    setActionLoading(false);
  }, [refetchStatus, refetchPortfolio]);

  const isRunning = botStatus?.is_running || false;

  const tabs = [
    { id: 'dashboard', label: 'Dashboard' },
    { id: 'chart', label: 'Chart' },
    { id: 'markets', label: 'Markets' },
    { id: 'settings', label: 'Settings' },
  ];

  return (
    <div className="app">
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
          <div className={`status-badge ${isRunning ? 'running' : 'stopped'}`}>
            <div className={`status-dot ${isRunning ? 'running' : 'stopped'}`} />
            {isRunning ? 'Running' : 'Stopped'}
          </div>
          {!isRunning ? (
            <button className="btn btn-success" onClick={handleStart} disabled={actionLoading}>
              Start Bot
            </button>
          ) : (
            <button className="btn btn-danger" onClick={handleStop} disabled={actionLoading}>
              Stop Bot
            </button>
          )}
          <button className="btn btn-outline" onClick={handleRunOnce} disabled={actionLoading}>
            Run Once
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
              <SettingsPanel settings={settingsData} />
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
              <SettingsPanel settings={settingsData} />
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
