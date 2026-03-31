import React from 'react';

function MarketsList({ markets = [], botStatus }) {
  const isPaper = botStatus?.trading_mode === 'paper';
  const lastSignal = botStatus?.last_signal;
  const selectedMarket = botStatus?.selected_market;

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '1.25rem' }}>
      {/* Active Market */}
      <div className="card">
        <div className="card-header">
          <span className="card-title">ACTIVE MARKET</span>
          <span style={{
            fontSize: '0.75rem',
            padding: '0.2rem 0.6rem',
            borderRadius: '4px',
            fontWeight: 700,
            background: 'rgba(59, 130, 246, 0.15)',
            color: '#3b82f6',
          }}>
            {isPaper ? 'PAPER MODE' : 'LIVE MODE'}
          </span>
        </div>

        <div style={{ padding: '1.5rem', textAlign: 'center' }}>
          <div style={{
            fontSize: '2rem',
            fontWeight: 800,
            color: 'var(--text-primary)',
            marginBottom: '0.5rem',
          }}>
            BTC 5min UP/DOWN
          </div>
          <div style={{
            fontSize: '0.9rem',
            color: 'var(--text-muted)',
            marginBottom: '1.5rem',
          }}>
            Trades BTC direction every 5 minutes using RSI, MACD, Momentum & Sentiment signals
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
                ({(lastSignal.confidence * 100).toFixed(0)}% conf)
              </span>
            </div>
          )}
        </div>
      </div>

      {/* Signal Breakdown */}
      <div className="card">
        <div className="card-header">
          <span className="card-title">SIGNAL SOURCES</span>
        </div>
        <div style={{ padding: '0' }}>
          {[
            { name: 'Binance 5min Candles', desc: 'Real-time BTCUSDT price data', status: true },
            { name: 'TradingView Scanner', desc: 'Pre-computed RSI, MACD, Stochastic, Momentum', status: true },
            { name: 'CoinTelegraph RSS', desc: 'News sentiment (bullish/bearish keywords)', status: true },
            { name: 'Regime Detection', desc: 'TREND / RANGE / CHAOTIC classification', status: true },
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
      </div>

      {/* Signal Details */}
      {lastSignal?.scores && (
        <div className="card">
          <div className="card-header">
            <span className="card-title">LAST SIGNAL DETAILS</span>
          </div>
          <div style={{ padding: '0' }}>
            {Object.entries(lastSignal.scores).map(([key, val], i, arr) => (
              <div key={key} style={{
                display: 'flex',
                justifyContent: 'space-between',
                padding: '0.6rem 1rem',
                borderBottom: i < arr.length - 1 ? '1px solid rgba(51, 65, 85, 0.3)' : 'none',
              }}>
                <span style={{ color: 'var(--text-secondary)', fontSize: '0.85rem' }}>
                  {key.replace(/_/g, ' ').replace(/tv /g, 'TV ').toUpperCase()}
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
          </div>

          {/* Reasons */}
          {lastSignal.reasons && lastSignal.reasons.length > 0 && (
            <div style={{ padding: '1rem', borderTop: '1px solid rgba(51, 65, 85, 0.3)' }}>
              <div style={{ fontSize: '0.75rem', color: 'var(--text-muted)', marginBottom: '0.5rem', fontWeight: 600 }}>REASONS:</div>
              {lastSignal.reasons.map((r, i) => (
                <div key={i} style={{
                  fontSize: '0.8rem',
                  color: 'var(--text-secondary)',
                  padding: '0.2rem 0',
                  fontFamily: 'monospace',
                }}>
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
