import React from 'react';

function TradesTable({ trades = [] }) {
  if (!trades.length) {
    return (
      <div className="card">
        <div className="card-header">
          <span className="card-title">Recent Trades</span>
        </div>
        <div className="loading">No trades yet. Start the bot to begin trading.</div>
      </div>
    );
  }

  return (
    <div className="card">
      <div className="card-header">
        <span className="card-title">Recent Trades</span>
        <span style={{ fontSize: '0.8rem', color: 'var(--text-muted)' }}>
          {trades.length} trades
        </span>
      </div>
      <div className="table-container">
        <table>
          <thead>
            <tr>
              <th>Time</th>
              <th>Market</th>
              <th>Side</th>
              <th>Price</th>
              <th>Size</th>
              <th>Cost</th>
              <th>P/L</th>
              <th>Status</th>
              <th>Signal</th>
            </tr>
          </thead>
          <tbody>
            {trades.map((trade, i) => (
              <tr key={trade.id || i}>
                <td>{trade.timestamp ? new Date(trade.timestamp).toLocaleTimeString() : '--'}</td>
                <td style={{ maxWidth: '200px', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', fontFamily: 'Inter, sans-serif' }}>
                  {trade.market_name?.substring(0, 40) || '--'}
                </td>
                <td className={trade.side === 'BUY' ? 'side-buy' : 'side-sell'}>
                  {trade.side}
                </td>
                <td>${trade.price?.toFixed(4)}</td>
                <td>{trade.size?.toFixed(2)}</td>
                <td>${trade.total_cost?.toFixed(2)}</td>
                <td className={(trade.pnl || 0) >= 0 ? 'positive' : 'negative'}>
                  ${(trade.pnl || 0).toFixed(2)}
                </td>
                <td>
                  <span className={`status-badge ${trade.status === 'filled' || trade.status === 'paper_trade' ? 'running' : 'stopped'}`}
                        style={{ display: 'inline-flex', fontSize: '0.7rem', padding: '0.15rem 0.5rem' }}>
                    {trade.status}
                  </span>
                </td>
                <td>{trade.signal_strength ? `${(trade.signal_strength * 100).toFixed(0)}%` : '--'}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

export default TradesTable;
