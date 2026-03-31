import React from 'react';

function MarketsList({ markets = [], botStatus }) {
  const lastSignal = botStatus?.last_signal;
  const selectedMarket = botStatus?.selected_market;

  // Separate primary BTC 5min market from Polymarket markets
  const primaryMarket = markets.find(m => m.is_primary || m.id === 'btc_5min_signal') || null;
  const polymarkets = markets.filter(m => !m.is_primary && m.id !== 'btc_5min_signal');

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '1.25rem' }}>
      {/* Primary Market: BTC 5min UP/DOWN */}
      <div className="card">
        <div className="card-header">
          <span className="card-title">ACTIVE TRADING MARKET</span>
          <span style={{
            fontSize: '0.7rem',
            padding: '0.2rem 0.5rem',
            borderRadius: '4px',
            fontWeight: 700,
            background: 'rgba(34, 197, 94, 0.15)',
            color: '#22c55e',
          }}>
            PRIMARY
          </span>
        </div>

        <div style={{ padding: '1.5rem', textAlign: 'center' }}>
          <div style={{
            fontSize: '2rem',
            fontWeight: 800,
            color: 'var(--text-primary)',
            marginBottom: '0.25rem',
          }}>
            BTC 5min UP/DOWN
          </div>
          <div style={{
            fontSize: '0.85rem',
            color: 'var(--text-muted)',
            marginBottom: '1.5rem',
          }}>
            Trades BTC direction every 5 minutes using Binance price + TradingView indicators + CoinTelegraph sentiment
          </div>

          {/* Current BTC Price */}
          {selectedMarket?.btc_entry_price > 0 && (
            <div style={{
              fontSize: '1.5rem',
              fontWeight: 700,
              color: 'var(--text-primary)',
              fontFamily: 'monospace',
              marginBottom: '1rem',
            }}>
              BTC ${selectedMarket.btc_entry_price.toLocaleString(undefined, { maximumFractionDigits: 0 })}
            </div>
          )}

          {/* Last Signal */}
          {lastSignal && (
            <div style={{
              display: 'inline-flex',
              alignItems: 'center',
              gap: '0.5rem',
              padding: '0.5rem 1.5rem',
              borderRadius: '10px',
              fontSize: '1.1rem',
              fontWeight: 700,
              background: lastSignal.direction === 'BUY'
                ? 'rgba(34, 197, 94, 0.15)'
                : lastSignal.direction === 'SELL'
                  ? 'rgba(239, 68, 68, 0.15)'
                  : 'rgba(51, 65, 85, 0.3)',
              color: lastSignal.direction === 'BUY' ? '#22c55e'
                : lastSignal.direction === 'SELL' ? '#ef4444'
                : 'var(--text-muted)',
            }}>
              {lastSignal.direction === 'BUY' ? '\u2191 UP' : lastSignal.direction === 'SELL' ? '\u2193 DOWN' : 'HOLD'}
              <span style={{ fontSize: '0.8rem', opacity: 0.7 }}>
                ({((lastSignal.confidence || 0) * 100).toFixed(0)}% conf)
              </span>
            </div>
          )}
        </div>
      </div>

      {/* Signal Sources */}
      <div className="card">
        <div className="card-header">
          <span className="card-title">DATA SOURCES</span>
        </div>
        {[
          { name: 'Binance BTCUSDT 5m', url: 'api.binance.com/api/v3/klines', desc: 'Real-time 5-minute candles' },
          { name: 'TradingView Scanner', url: 'scanner.tradingview.com/crypto/scan', desc: 'RSI, MACD, Stochastic, Momentum' },
          { name: 'CoinTelegraph RSS', url: 'cointelegraph.com/rss/tag/bitcoin', desc: 'News sentiment analysis' },
          { name: 'Gamma API (Polymarket)', url: 'gamma-api.polymarket.com/markets', desc: 'BTC prediction market discovery' },
        ].map((source, i) => (
          <div key={i} style={{
            display: 'flex',
            justifyContent: 'space-between',
            alignItems: 'center',
            padding: '0.75rem 1rem',
            borderBottom: i < 3 ? '1px solid rgba(51, 65, 85, 0.3)' : 'none',
          }}>
            <div>
              <div style={{ fontWeight: 600, fontSize: '0.85rem', color: 'var(--text-primary)' }}>{source.name}</div>
              <div style={{ fontSize: '0.7rem', color: 'var(--text-muted)', fontFamily: 'monospace' }}>{source.url}</div>
              <div style={{ fontSize: '0.75rem', color: 'var(--text-muted)' }}>{source.desc}</div>
            </div>
            <span style={{
              fontSize: '0.7rem',
              fontWeight: 700,
              padding: '0.15rem 0.5rem',
              borderRadius: '4px',
              background: 'rgba(34, 197, 94, 0.15)',
              color: '#22c55e',
            }}>
              ACTIVE
            </span>
          </div>
        ))}
      </div>

      {/* Polymarket BTC Markets (from Gamma API) */}
      {polymarkets.length > 0 && (
        <div className="card">
          <div className="card-header">
            <span className="card-title">POLYMARKET BTC MARKETS</span>
            <span style={{ fontSize: '0.75rem', color: 'var(--text-muted)' }}>
              from gamma-api.polymarket.com | {polymarkets.length} found
            </span>
          </div>
          <div className="table-container">
            <table>
              <thead>
                <tr>
                  <th>Market</th>
                  <th>Yes</th>
                  <th>No</th>
                  <th>Volume</th>
                </tr>
              </thead>
              <tbody>
                {polymarkets.map((market, i) => (
                  <tr key={market.id || i}>
                    <td style={{ maxWidth: '300px', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', fontSize: '0.8rem' }}>
                      {market.question}
                    </td>
                    <td style={{ color: 'var(--green)', fontFamily: 'monospace' }}>{market.yes_price?.toFixed(2)}</td>
                    <td style={{ color: 'var(--red)', fontFamily: 'monospace' }}>{market.no_price?.toFixed(2)}</td>
                    <td style={{ fontFamily: 'monospace', fontSize: '0.8rem' }}>${(market.volume || 0).toLocaleString()}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* Signal Details */}
      {lastSignal?.scores && (
        <div className="card">
          <div className="card-header">
            <span className="card-title">LAST SIGNAL BREAKDOWN</span>
          </div>
          {Object.entries(lastSignal.scores).map(([key, val], i, arr) => (
            <div key={key} style={{
              display: 'flex',
              justifyContent: 'space-between',
              padding: '0.6rem 1rem',
              borderBottom: i < arr.length - 1 ? '1px solid rgba(51, 65, 85, 0.3)' : 'none',
            }}>
              <span style={{ color: 'var(--text-secondary)', fontSize: '0.85rem' }}>
                {key.replace(/_/g, ' ').toUpperCase()}
              </span>
              <span style={{
                fontFamily: 'monospace',
                fontWeight: 600,
                color: val > 0 ? 'var(--green)' : val < 0 ? 'var(--red)' : 'var(--text-muted)',
              }}>
                {typeof val === 'number' ? val.toFixed(4) : val}
              </span>
            </div>
          ))}

          {lastSignal.reasons && lastSignal.reasons.length > 0 && (
            <div style={{ padding: '1rem', borderTop: '1px solid rgba(51, 65, 85, 0.3)' }}>
              <div style={{ fontSize: '0.75rem', color: 'var(--text-muted)', marginBottom: '0.5rem', fontWeight: 600 }}>REASONS:</div>
              {lastSignal.reasons.map((r, i) => (
                <div key={i} style={{ fontSize: '0.78rem', color: 'var(--text-secondary)', padding: '0.15rem 0', fontFamily: 'monospace' }}>
                  {r}
                </div>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

export default MarketsList;
