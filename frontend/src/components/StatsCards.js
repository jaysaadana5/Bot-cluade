import React from 'react';

function StatsCards({ portfolio, botStatus, sentiment }) {
  const stats = [
    {
      label: 'Total P/L',
      value: portfolio ? `$${portfolio.total_pnl?.toFixed(2) || '0.00'}` : '--',
      change: portfolio?.pnl_pct ? `${portfolio.pnl_pct > 0 ? '+' : ''}${portfolio.pnl_pct}%` : null,
      changeClass: (portfolio?.total_pnl || 0) >= 0 ? 'positive' : 'negative',
    },
    {
      label: 'Total Trades',
      value: portfolio?.total_trades || 0,
      change: `Win Rate: ${portfolio?.win_rate || 0}%`,
      changeClass: (portfolio?.win_rate || 0) >= 50 ? 'positive' : 'neutral',
    },
    {
      label: 'Sentiment',
      value: sentiment ? (sentiment.score > 0 ? 'Bullish' : sentiment.score < 0 ? 'Bearish' : 'Neutral') : '--',
      change: sentiment ? `Score: ${sentiment.score?.toFixed(3) || '0'}` : null,
      changeClass: (sentiment?.score || 0) > 0 ? 'positive' : (sentiment?.score || 0) < 0 ? 'negative' : 'neutral',
    },
    {
      label: 'Bot Cycles',
      value: botStatus?.cycle_count || 0,
      change: botStatus?.is_running ? 'Active' : 'Stopped',
      changeClass: botStatus?.is_running ? 'positive' : 'negative',
    },
  ];

  return (
    <div className="grid grid-4">
      {stats.map((stat, i) => (
        <div key={i} className="card">
          <div className="stat-label">{stat.label}</div>
          <div className="stat-value">{stat.value}</div>
          {stat.change && (
            <div className={`stat-change ${stat.changeClass}`}>{stat.change}</div>
          )}
        </div>
      ))}
    </div>
  );
}

export default StatsCards;
