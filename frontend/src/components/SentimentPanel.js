import React from 'react';
import { AreaChart, Area, XAxis, YAxis, Tooltip, ResponsiveContainer } from 'recharts';

function SentimentPanel({ sentiment, history = [] }) {
  const score = sentiment?.score || 0;
  const markerPos = ((score + 1) / 2) * 100; // -1..1 => 0..100%
  const details = sentiment?.details || {};

  return (
    <div className="card">
      <div className="card-header">
        <span className="card-title">Polymarket Sentiment</span>
        <span style={{ fontSize: '0.8rem', color: 'var(--text-muted)' }}>
          {sentiment?.market || 'BTC 5min UP/DOWN'}
        </span>
      </div>

      {/* Sentiment Meter */}
      <div style={{ marginBottom: '1rem' }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '0.75rem', color: 'var(--text-muted)', marginBottom: '0.25rem' }}>
          <span>Bearish (DOWN)</span>
          <span>Neutral</span>
          <span>Bullish (UP)</span>
        </div>
        <div className="sentiment-bar">
          <div className="sentiment-marker" style={{ left: `${markerPos}%` }} />
        </div>
      </div>

      {/* Polymarket Odds */}
      <div style={{ display: 'flex', gap: '1.5rem', marginBottom: '1rem', flexWrap: 'wrap' }}>
        <div>
          <div className="stat-label">Score</div>
          <div className={`stat-value ${score > 0 ? 'positive' : score < 0 ? 'negative' : 'neutral'}`}
               style={{ fontSize: '1.25rem' }}>
            {score.toFixed(3)}
          </div>
        </div>
        {details.yes_price != null && (
          <div>
            <div className="stat-label">YES (UP)</div>
            <div className="positive" style={{ fontWeight: 700, fontSize: '1.1rem' }}>
              {(details.yes_price * 100).toFixed(1)}%
            </div>
          </div>
        )}
        {details.no_price != null && (
          <div>
            <div className="stat-label">NO (DOWN)</div>
            <div className="negative" style={{ fontWeight: 700, fontSize: '1.1rem' }}>
              {(details.no_price * 100).toFixed(1)}%
            </div>
          </div>
        )}
        <div>
          <div className="stat-label">Confidence</div>
          <div style={{ fontWeight: 600 }}>{((sentiment?.confidence || 0) * 100).toFixed(0)}%</div>
        </div>
      </div>

      {/* Sentiment Breakdown */}
      {(details.buy_pressure != null || details.spread != null) && (
        <div style={{
          padding: '0.75rem',
          background: 'var(--bg-primary)',
          borderRadius: '8px',
          marginBottom: '1rem',
        }}>
          <div className="stat-label" style={{ marginBottom: '0.5rem' }}>Market Data</div>
          <div style={{ display: 'flex', gap: '1.5rem', flexWrap: 'wrap', fontSize: '0.85rem' }}>
            {details.buy_pressure != null && (
              <div>
                <span style={{ color: 'var(--text-muted)' }}>Buy Pressure: </span>
                <span className="mono" style={{
                  fontWeight: 600,
                  color: details.buy_pressure > 0.55 ? 'var(--green)' : details.buy_pressure < 0.45 ? 'var(--red)' : 'var(--text-primary)',
                }}>
                  {(details.buy_pressure * 100).toFixed(0)}%
                </span>
              </div>
            )}
            {details.spread != null && details.spread > 0 && (
              <div>
                <span style={{ color: 'var(--text-muted)' }}>Spread: </span>
                <span className="mono" style={{ fontWeight: 600 }}>
                  {(details.spread * 100).toFixed(2)}%
                </span>
              </div>
            )}
            {details.bid_volume != null && (
              <div>
                <span style={{ color: 'var(--text-muted)' }}>Bids: </span>
                <span className="mono positive" style={{ fontWeight: 600 }}>
                  {details.bid_volume.toFixed(0)}
                </span>
              </div>
            )}
            {details.ask_volume != null && (
              <div>
                <span style={{ color: 'var(--text-muted)' }}>Asks: </span>
                <span className="mono negative" style={{ fontWeight: 600 }}>
                  {details.ask_volume.toFixed(0)}
                </span>
              </div>
            )}
          </div>
        </div>
      )}

      {/* History Chart */}
      {history.length > 0 && (
        <div style={{ height: '120px', marginTop: '0.5rem' }}>
          <ResponsiveContainer width="100%" height="100%">
            <AreaChart data={history.slice().reverse()}>
              <defs>
                <linearGradient id="sentGrad" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="5%" stopColor="#3b82f6" stopOpacity={0.3} />
                  <stop offset="95%" stopColor="#3b82f6" stopOpacity={0} />
                </linearGradient>
              </defs>
              <XAxis dataKey="timestamp" hide />
              <YAxis domain={[-1, 1]} hide />
              <Tooltip
                contentStyle={{ background: '#1e293b', border: '1px solid #334155', borderRadius: '8px', fontSize: '0.8rem' }}
                labelStyle={{ color: '#94a3b8' }}
              />
              <Area type="monotone" dataKey="score" stroke="#3b82f6" fill="url(#sentGrad)" />
            </AreaChart>
          </ResponsiveContainer>
        </div>
      )}

      {/* Source note */}
      {sentiment?.note && (
        <div style={{ marginTop: '0.75rem', fontSize: '0.75rem', color: 'var(--text-muted)' }}>
          {sentiment.note}
        </div>
      )}
    </div>
  );
}

export default SentimentPanel;
