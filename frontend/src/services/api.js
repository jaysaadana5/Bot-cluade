import axios from 'axios';

const API_BASE = process.env.REACT_APP_API_URL || 'http://localhost:8000';

const api = axios.create({
  baseURL: `${API_BASE}/api`,
  timeout: 30000,
});

// Bot Control
export const startBot = () => api.post('/bot/start');
export const stopBot = () => api.post('/bot/stop');
export const getBotStatus = () => api.get('/bot/status');
export const runBotOnce = () => api.post('/bot/run-once');
export const getBotHistory = () => api.get('/bot/history');

// Markets
export const getMarkets = () => api.get('/markets');
export const getMarket = (id) => api.get(`/markets/${id}`);
export const getOrderbook = (tokenId) => api.get(`/markets/${tokenId}/orderbook`);
export const getPriceHistory = (tokenId, fidelity = 5) =>
  api.get(`/markets/${tokenId}/price-history`, { params: { fidelity } });

// Sentiment
export const getSentiment = () => api.get('/sentiment');
export const getSentimentHistory = (limit = 50) =>
  api.get('/sentiment/history', { params: { limit } });
export const getTrending = () => api.get('/sentiment/trending');

// Portfolio
export const getPortfolio = () => api.get('/portfolio');
export const getTrades = (limit = 50, offset = 0) =>
  api.get('/trades', { params: { limit, offset } });

// Snapshots
export const getSnapshots = (limit = 100) =>
  api.get('/snapshots', { params: { limit } });

// Settings
export const getSettings = () => api.get('/settings');

// Health
export const getHealth = () => axios.get(`${API_BASE}/health`);

export default api;
