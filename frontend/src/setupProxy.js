const { createProxyMiddleware } = require('http-proxy-middleware');

// Proxy API requests from the dev server to the backend.
// This makes development work when frontend is served from a forwarded/public URL
// (requests to `/api/*` will be proxied to the backend on localhost:8000).

const target = process.env.REACT_APP_BACKEND_URL || 'http://localhost:8000';

module.exports = function (app) {
  app.use(
    ['/api', '/auth', '/profile', '/uploads'],
    createProxyMiddleware({
      target,
      changeOrigin: true,
      secure: false,
      logLevel: 'warn',
    })
  );
};
