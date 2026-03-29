import React, { useMemo } from 'react';
import {
  AreaChart, Area, XAxis, YAxis, Tooltip,
  ResponsiveContainer, CartesianGrid,
} from 'recharts';

function PnLChart({ trades = [] }) {
  const chartData = useMemo(() => {
    if (!trades.length) return [];

    const sorted = [...trades].reverse();
    let cumPnl = 0;
    return sorted.map((t) => {
      cumPnl += t.pnl || 0;
      return {
        time: t.timestamp ? new Date(t.timestamp).toLocaleTimeString() : '',
        pnl: t.pnl || 0,
        cumulative: parseFloat(cumPnl.toFixed(2)),
        cost: t.total_cost || 0,
      };
    });
  }, [trades]);

  if (!chartData.length) {
    return (
      <div className="card">
        <div className="card-header">
          <span className="card-title">P/L Performance</span>
        </div>
        <div className="loading">No trade data yet.</div>
      </div>
    );
  }

  const lastPnl = chartData[chartData.length - 1]?.cumulative || 0;
  const color = lastPnl >= 0 ? '#22c55e' : '#ef4444';

  return (
    <div className="card">
      <div className="card-header">
        <span className="card-title">P/L Performance</span>
        <span className={`mono ${lastPnl >= 0 ? 'positive' : 'negative'}`} style={{ fontWeight: 700 }}>
          ${lastPnl.toFixed(2)}
        </span>
      </div>
      <div style={{ height: '220px' }}>
        <ResponsiveContainer width="100%" height="100%">
          <AreaChart data={chartData}>
            <defs>
              <linearGradient id="pnlGrad" x1="0" y1="0" x2="0" y2="1">
                <stop offset="5%" stopColor={color} stopOpacity={0.3} />
                <stop offset="95%" stopColor={color} stopOpacity={0} />
              </linearGradient>
            </defs>
            <CartesianGrid strokeDasharray="3 3" stroke="#1e293b" />
            <XAxis dataKey="time" tick={{ fontSize: 10, fill: '#64748b' }} />
            <YAxis tick={{ fontSize: 10, fill: '#64748b' }} />
            <Tooltip
              contentStyle={{
                background: '#1e293b',
                border: '1px solid #334155',
                borderRadius: '8px',
                fontSize: '0.8rem',
              }}
            />
            <Area
              type="monotone"
              dataKey="cumulative"
              stroke={color}
              fill="url(#pnlGrad)"
              strokeWidth={2}
              name="Cumulative P/L"
            />
          </AreaChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
}

export default PnLChart;
