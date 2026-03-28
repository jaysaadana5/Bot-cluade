import React, { useEffect, useRef, memo } from 'react';

/**
 * TradingView Advanced Chart Widget
 * Embeds TradingView chart for BTC price visualization.
 * You can customize the symbol via props.
 */
function TradingViewChart({ symbol = 'BTCUSD', theme = 'dark', height = 500 }) {
  const containerRef = useRef(null);

  useEffect(() => {
    if (!containerRef.current) return;

    // Clear previous widget
    containerRef.current.innerHTML = '';

    const script = document.createElement('script');
    script.src = 'https://s3.tradingview.com/external-embedding/embed-widget-advanced-chart.js';
    script.type = 'text/javascript';
    script.async = true;
    script.innerHTML = JSON.stringify({
      autosize: true,
      symbol: symbol,
      interval: '5',
      timezone: 'Etc/UTC',
      theme: theme,
      style: '1',
      locale: 'en',
      allow_symbol_change: true,
      support_host: 'https://www.tradingview.com',
      hide_side_toolbar: false,
      details: true,
      hotlist: false,
      calendar: false,
      studies: [
        'STD;RSI',
        'STD;MACD',
        'STD;Bollinger_Bands',
      ],
      container_id: 'tradingview_widget',
    });

    containerRef.current.appendChild(script);
  }, [symbol, theme]);

  return (
    <div className="card" style={{ padding: 0, overflow: 'hidden' }}>
      <div className="card-header" style={{ padding: '0.75rem 1.25rem', margin: 0 }}>
        <span className="card-title">BTC Chart (TradingView)</span>
        <span style={{ fontSize: '0.8rem', color: 'var(--text-muted)' }}>
          {symbol} | 5m
        </span>
      </div>
      <div
        id="tradingview_widget"
        ref={containerRef}
        className="tradingview-container"
        style={{ height: `${height}px` }}
      />
    </div>
  );
}

export default memo(TradingViewChart);
