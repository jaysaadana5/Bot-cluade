import React, { useState, useEffect } from 'react';

function CountdownTimer({ secondsUntilNext, isRunning }) {
  const [seconds, setSeconds] = useState(secondsUntilNext || 0);

  useEffect(() => {
    setSeconds(secondsUntilNext || 0);
  }, [secondsUntilNext]);

  useEffect(() => {
    if (!isRunning || seconds <= 0) return;
    const timer = setInterval(() => {
      setSeconds((s) => Math.max(0, s - 1));
    }, 1000);
    return () => clearInterval(timer);
  }, [isRunning, seconds]);

  const mins = Math.floor(seconds / 60);
  const secs = seconds % 60;
  const pct = secondsUntilNext > 0 ? ((secondsUntilNext - seconds) / secondsUntilNext) * 100 : 0;

  return (
    <div>
      <div style={{ fontSize: '1.5rem', fontWeight: 700, fontFamily: 'monospace', color: seconds < 30 ? 'var(--green)' : 'var(--text-primary)' }}>
        {isRunning ? `${mins}:${secs.toString().padStart(2, '0')}` : '--:--'}
      </div>
      {isRunning && (
        <div style={{ marginTop: '0.5rem', height: '4px', borderRadius: '2px', background: 'rgba(51, 65, 85, 0.5)', overflow: 'hidden' }}>
          <div style={{ height: '100%', width: `${pct}%`, background: 'var(--blue)', borderRadius: '2px', transition: 'width 1s linear' }} />
        </div>
      )}
    </div>
  );
}

function StatsCards({ portfolio, botStatus, sentiment }) {
  const totalPnl = portfolio?.total_pnl || 0;
  const winRate = portfolio?.win_rate || 0;
  const isRunning = botStatus?.is_running || false;

  const stats = [
    {
      label: 'Total P/L',
      value: `$${totalPnl >= 0 ? '+' : ''}${totalPnl.toFixed(2)}`,
      change: portfolio?.pnl_pct ? `${portfolio.pnl_pct > 0 ? '+' : ''}${portfolio.pnl_pct}%` : null,
      changeClass: totalPnl >= 0 ? 'positive' : 'negative',
      valueColor: totalPnl > 0 ? 'var(--green)' : totalPnl < 0 ? 'var(--red)' : 'var(--text-primary)',
    },
    {
      label: 'Total Trades',
      value: portfolio?.total_trades || 0,
      change: `Win: ${portfolio?.wins || 0} | Loss: ${portfolio?.losses || 0} | Rate: ${winRate}%`,
      changeClass: winRate >= 50 ? 'positive' : 'neutral',
    },
    {
      label: 'Sentiment',
      value: sentiment ? (sentiment.score > 0 ? 'Bullish' : sentiment.score < 0 ? 'Bearish' : 'Neutral') : '--',
      change: sentiment ? `Score: ${sentiment.score?.toFixed(3) || '0'}` : null,
      changeClass: (sentiment?.score || 0) > 0 ? 'positive' : (sentiment?.score || 0) < 0 ? 'negative' : 'neutral',
    },
  ];

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '1.25rem' }}>
      <div className="grid grid-4">
        {stats.map((stat, i) => (
          <div key={i} className="card">
            <div className="stat-label">{stat.label}</div>
            <div className="stat-value" style={stat.valueColor ? { color: stat.valueColor } : {}}>{stat.value}</div>
            {stat.change && (
              <div className={`stat-change ${stat.changeClass}`}>{stat.change}</div>
            )}
          </div>
        ))}

        {/* Timer Card */}
        <div className="card">
          <div className="stat-label">Next Trade In</div>
          <CountdownTimer
            secondsUntilNext={botStatus?.seconds_until_next || 0}
            isRunning={isRunning}
          />
          <div className={`stat-change ${isRunning ? 'positive' : 'negative'}`}>
            {isRunning
              ? `Cycle #${botStatus?.cycle_count || 0} | Trades in last 30 sec`
              : 'Bot Stopped'}
          </div>
          {isRunning && botStatus?.seconds_until_close != null && (
            <div style={{ fontSize: '0.7rem', color: 'var(--text-muted)', marginTop: '0.25rem' }}>
              Window {botStatus.window_start || ''}-{botStatus.window_end || ''} | {botStatus.seconds_until_close}s to close
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

export default StatsCards;
