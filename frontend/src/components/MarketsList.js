import React from 'react';

function MarketsList({ markets = [] }) {
  return (
    <div className="card">
      <div className="card-header">
        <span className="card-title">BTC Markets</span>
        <span style={{ fontSize: '0.8rem', color: 'var(--text-muted)' }}>
          {markets.length} active
        </span>
      </div>

      {markets.length === 0 ? (
        <div className="loading">No BTC markets found. Click refresh or wait for next cycle.</div>
      ) : (
        <div className="table-container">
          <table>
            <thead>
              <tr>
                <th>Market</th>
                <th>Yes</th>
                <th>No</th>
                <th>Volume</th>
                <th>Liquidity</th>
              </tr>
            </thead>
            <tbody>
              {markets.map((market, i) => (
                <tr key={market.id || i}>
                  <td style={{ fontFamily: 'Inter, sans-serif', maxWidth: '300px', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                    {market.question}
                  </td>
                  <td className="positive">${market.yes_price?.toFixed(2)}</td>
                  <td className="negative">${market.no_price?.toFixed(2)}</td>
                  <td>${(market.volume || 0).toLocaleString()}</td>
                  <td>${(market.liquidity || 0).toLocaleString()}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

export default MarketsList;
