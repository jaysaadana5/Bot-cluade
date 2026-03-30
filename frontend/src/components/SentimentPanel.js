import React from 'react';
import { AreaChart, Area, XAxis, YAxis, Tooltip, ResponsiveContainer } from 'recharts';

function SentimentPanel({ sentiment, history = [] }) {
  const score = sentiment?.score || 0;
  const markerPos = ((score + 1) / 2) * 100; // -1..1 => 0..100%

  return (
    <div className="card">
      <div className="card-header">
        <span className="card-title">CoinTelegraph Sentiment</span>
        {sentiment?.tweet_count > 0 && (
          <span style={{ fontSize: '0.8rem', color: 'var(--text-muted)' }}>
            {sentiment.tweet_count} articles analyzed
          </span>
        )}
      </div>

      {/* Sentiment Meter */}
      <div style={{ marginBottom: '1rem' }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '0.75rem', color: 'var(--text-muted)', marginBottom: '0.25rem' }}>
          <span>Bearish</span>
          <span>Neutral</span>
          <span>Bullish</span>
        </div>
        <div className="sentiment-bar">
          <div className="sentiment-marker" style={{ left: `${markerPos}%` }} />
        </div>
      </div>

      {/* Score Display */}
      <div style={{ display: 'flex', gap: '1.5rem', marginBottom: '1rem' }}>
        <div>
          <div className="stat-label">Score</div>
          <div className={`stat-value ${score > 0 ? 'positive' : score < 0 ? 'negative' : 'neutral'}`}
               style={{ fontSize: '1.25rem' }}>
            {score.toFixed(3)}
          </div>
        </div>
        <div>
          <div className="stat-label">Bullish</div>
          <div className="positive" style={{ fontWeight: 600 }}>{sentiment?.bullish || 0}</div>
        </div>
        <div>
          <div className="stat-label">Bearish</div>
          <div className="negative" style={{ fontWeight: 600 }}>{sentiment?.bearish || 0}</div>
        </div>
        <div>
          <div className="stat-label">Confidence</div>
          <div style={{ fontWeight: 600 }}>{((sentiment?.confidence || 0) * 100).toFixed(0)}%</div>
        </div>
      </div>

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

      {/* Top Headlines */}
      {sentiment?.top_tweets?.length > 0 && (
        <div style={{ marginTop: '1rem' }}>
          <div className="stat-label" style={{ marginBottom: '0.5rem' }}>Top Headlines</div>
          {sentiment.top_tweets.slice(0, 3).map((article, i) => (
            <div key={i} style={{
              padding: '0.5rem',
              background: 'var(--bg-primary)',
              borderRadius: '6px',
              marginBottom: '0.4rem',
              fontSize: '0.8rem',
              color: 'var(--text-secondary)',
            }}>
              <span className={article.sentiment === 'bullish' ? 'positive' : article.sentiment === 'bearish' ? 'negative' : ''}>
                [{article.sentiment}]
              </span>{' '}
              {article.text?.substring(0, 120)}{article.text?.length > 120 ? '...' : ''}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

export default SentimentPanel;
