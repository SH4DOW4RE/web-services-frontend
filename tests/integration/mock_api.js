// Runs before frontend/api.js and frontend/script.js on each browser navigation.
// A deterministic, stateful API simulator IN the browser (no Prism, network, or server writes).
(() => {
  'use strict';
  const USER_ID = '27463fb9-feaf-4a30-a942-35b37ea541d4';
  const PRODUCTS = [
    { uuid: '4b95dd13-708d-4419-b2e2-c7520a11d1a1', seller: {uuid: USER_ID, username: 'bob_123'}, name: 'Hoodie', images: [], stock: 10, price: 39.95, sizes: ['M','L'], colors: ['black'] },
    { uuid: '4b95dd13-708d-4419-b2e2-c7520a11d1a2', seller: {uuid: USER_ID, username: 'bob_123'}, name: 'T-Shirt', images: [], stock: 4, price: 12.50, sizes: ['S','M'], colors: ['blue'] },
    { uuid: '4b95dd13-708d-4419-b2e2-c7520a11d1a3', seller: {uuid: USER_ID, username: 'bob_123'}, name: 'Jeans', images: [], stock: 7, price: 60.00, sizes: ['M'], colors: ['gray'] },
  ];
  const clone = obj => JSON.parse(JSON.stringify(obj));
  const state = {
    products: clone(PRODUCTS),
    cart: [],
    user: null,
    requests: [],
    // { method: 'GET', path: '/products', status: 503, message: 'offline' }
    failNext: null,
  };
  window.__mockMarket = state;
  window.fetch = async (input, options = {}) => {
    const url = new URL(typeof input === 'string' ? input : input.url, window.location.href);
    const method = (options.method || 'GET').toUpperCase();
    const path = url.pathname;
    const body = options.body ? JSON.parse(options.body) : null;
    const event = {method, path, query: url.search, body, credentials: options.credentials || 'same-origin'};
    state.requests.push(event);
    const json = (status, data = null) => {
      event.status = status;
      return new Response(data == null ? null : JSON.stringify(data), {
        status, headers: data == null ? {} : { 'Content-Type': 'application/json' }
      });
    };
    const error = (status, message) => json(status, {code: status, message});
    if (state.failNext && state.failNext.method === method && state.failNext.path === path) {
      const {status, message} = state.failNext;
      state.failNext = null;
      return error(status, message || 'Forced test failure');
    }
    if (method === 'GET' && path === '/health') return json(200, {status: 'All systems operational.'});
    if (method === 'GET' && path === '/products') return json(200, clone(state.products));
    if (method === 'GET' && path === '/products/search') {
      const query = (url.searchParams.get('q') || '').toLowerCase();
      const found = state.products.filter(x => x.name.toLowerCase().includes(query));
      return found.length ? json(200, clone(found)) : error(404, 'No Products found.');
    }
    if (method === 'GET' && path.startsWith('/products/')) {
      const found = state.products.find(x => x.uuid === decodeURIComponent(path.slice('/products/'.length)));
      return found ? json(200, clone(found)) : error(404, 'Product Not Found.');
    }
    if (method === 'POST' && path === '/user/login') {
      if (body.username !== 'bob_123' || body.password !== 'abcdAB123!@')
        return error(401, 'Invalid Username or Password.');
      state.user = {uuid: USER_ID, username: 'bob_123'};
      return json(200, clone(state.user));
    }
    if (method === 'POST' && path === '/user/register') {
      if (body.username === 'bob_123') return error(409, 'Username already taken.');
      return json(200, {uuid: USER_ID, username: body.username});
    }
    if (method === 'GET' && path === '/user/logout') { state.user = null; return json(200); }
    if (method === 'PATCH' && path === '/user') {
      if (!state.user) return error(401, 'Please sign in.');
      if (body.uuid !== state.user.uuid) return error(404, 'User not found.');
      if (body.username) state.user.username = body.username;
      return json(200, clone(state.user));
    }
    if (method === 'DELETE' && path === '/user') { state.user = null; return json(200); }
    if (method === 'GET' && path === '/cart') {
      if (!state.cart.length) return error(404, 'Cart is empty.');
      return json(200, {owner: clone(state.user || {uuid: USER_ID, username: 'bob_123'}), items: clone(state.cart)});
    }
    if (method === 'POST' && path === '/cart') {
      if (!state.user) return error(401, 'Please sign in.');
      const found = state.products.find(x => x.uuid === body?.product);
      if (!found) return error(404, 'Product Not Found.');
      if (!Number.isInteger(body.quantity) || body.quantity < 1 || body.quantity > 1000)
        return error(400, 'Bad quantity.');
      const row = state.cart.find(x => x.uuid === found.uuid);
      if (row) row.quantity += body.quantity;
      else state.cart.push({...clone(found), quantity: body.quantity});
      return json(200);
    }
    if (path === '/cart' && ['PATCH','DELETE'].includes(method)) {
      const index = Number(url.searchParams.get('index'));
      if (!Number.isInteger(index) || index < 0 || index >= state.cart.length) return error(404, 'Cart Product Not Found.');
      if (method === 'PATCH') {
        if (!Number.isInteger(body.quantity) || body.quantity < 1 || body.quantity > 1000)
          return error(400, 'Bad quantity.');
        state.cart[index].quantity = body.quantity;
      } else state.cart.splice(index, 1);
      return json(200);
    }
    if (method === 'DELETE' && path === '/cart/clear') { state.cart = []; return json(200); }
    return error(404, `Unhandled mock route: ${method} ${path}`);
  };
})();
