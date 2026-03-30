import React from 'react';

function TradesTable({ trades = [] }) {
  if (!trades.length) {
    return (
      <div className="card">
        <div className="card-header">
          <span className="card-title">TRADE HISTORY</span>
        </div>
        <div className="loading">No trades yet. Click "Start Bot" to begin trading BTC 5min signals.</div>
      </div>
    );
  }

  const totalPnl = trades.reduce((sum, t) => sum + (t.pnl || 0), 0);
  const settled = trades.filter(t => t.status === 'settled');
  const wins = settled.filter(t => (t.pnl || 0) > 0).length;
  const losses = settled.filter(t => (t.pnl || 0) < 0).length;

  return (
    <div className="card">
      <div className="card-header">
        <span className="card-title">TRADE HISTORY</span>
        <div style={{ display: 'flex', gap: '1rem', fontSize: '0.8rem' }}>
          <span style={{ color: 'var(--text-muted)' }}>{trades.length} trades</span>
          <span style={{ color: totalPnl >= 0 ? 'var(--green)' : 'var(--red)', fontWeight: 700 }}>
            P&L: ${totalPnl >= 0 ? '+' : ''}{totalPnl.toFixed(2)}
          </span>
          {settled.length > 0 && (
            <span style={{ color: 'var(--text-muted)' }}>
              W:{wins} L:{losses}
            </span>
          )}
        </div>
      </div>
      <div className="table-container">
        <table>
          <thead>
            <tr>
              <th>Time</th>
              <th>Signal</th>
              <th>BTC Price</th>
              <th>Amount</th>
              <th>Confidence</th>
              <th>P/L</th>
              <th>Status</th>
            </tr>
          </thead>
          <tbody>
            {trades.map((trade, i) => {
              const pnl = trade.pnl || 0;
              const isSettled = trade.status === 'settled';
              const isPending = trade.status === 'paper_filled';
              return (
                <tr key={trade.id || i}>
                  <td style={{ fontSize: '0.8rem', whiteSpace: 'nowrap' }}>
                    {trade.timestamp ? new Date(trade.timestamp).toLocaleTimeString() : '--'}
                  </td>
                  <td>
                    <span style={{
                      display: 'inline-flex',
                      alignItems: 'center',
                      gap: '0.3rem',
                      padding: '0.2rem 0.6rem',
                      borderRadius: '6px',
                      fontWeight: 700,
                      fontSize: '0.8rem',
                      background: trade.side === 'BUY' ? 'rgba(34, 197, 94, 0.15)' : 'rgba(239, 68, 68, 0.15)',
                      color: trade.side === 'BUY' ? '#22c55e' : '#ef4444',
                    }}>
                      {trade.side === 'BUY' ? 'UP' : 'DOWN'} {trade.side === 'BUY' ? '\u2191' : '\u2193'}
                    </span>
                  </td>
                  <td style={{ fontFamily: 'monospace', fontWeight: 600 }}>
                    ${trade.price > 100 ? trade.price.toLocaleString(undefined, { maximumFractionDigits: 0 }) : trade.price?.toFixed(4)}
                  </td>
                  <td style={{ fontWeight: 600 }}>
                    ${trade.size?.toFixed(2) || trade.total_cost?.toFixed(2)}
                  </td>
                  <td>
                    <div style={{
                      display: 'flex',
                      alignItems: 'center',
                      gap: '0.3rem',
                    }}>
                      <div style={{
                        width: '40px',
                        height: '4px',
                        borderRadius: '2px',
                        background: 'rgba(51, 65, 85, 0.5)',
                        overflow: 'hidden',
                      }}>
                        <div style={{
                          height: '100%',
                          width: `${(trade.signal_strength || 0) * 100}%`,
                          background: (trade.signal_strength || 0) > 0.5 ? 'var(--green)' : 'var(--yellow)',
                          borderRadius: '2px',
                        }} />
                      </div>
                      <span style={{ fontSize: '0.75rem', color: 'var(--text-muted)' }}>
                        {trade.signal_strength ? `${(trade.signal_strength * 100).toFixed(0)}%` : '--'}
                      </span>
                    </div>
                  </td>
                  <td style={{
                    fontWeight: 700,
                    fontFamily: 'monospace',
                    color: isSettled
                      ? (pnl > 0 ? 'var(--green)' : pnl < 0 ? 'var(--red)' : 'var(--text-muted)')
                      : 'var(--yellow)',
                  }}>
                    {isSettled
                      ? `${pnl >= 0 ? '+' : ''}$${pnl.toFixed(2)}`
                      : isPending ? 'Pending...' : `$${pnl.toFixed(2)}`}
                  </td>
                  <td>
                    <span style={{
                      display: 'inline-flex',
                      fontSize: '0.7rem',
                      padding: '0.15rem 0.5rem',
                      borderRadius: '4px',
                      fontWeight: 600,
                      background: isSettled
                        ? (pnl > 0 ? 'rgba(34, 197, 94, 0.15)' : pnl < 0 ? 'rgba(239, 68, 68, 0.15)' : 'rgba(51, 65, 85, 0.3)')
                        : 'rgba(234, 179, 8, 0.15)',
                      color: isSettled
                        ? (pnl > 0 ? '#22c55e' : pnl < 0 ? '#ef4444' : 'var(--text-muted)')
                        : '#eab308',
                    }}>
                      {isSettled ? (pnl > 0 ? 'WIN' : pnl < 0 ? 'LOSS' : 'EVEN') : 'OPEN'}
                    </span>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}

export default TradesTable;
