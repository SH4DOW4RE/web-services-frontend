'use strict';
const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const source = fs.readFileSync(path.join(__dirname, '../../frontend/api.js'), 'utf8');
const UUID = '27463fb9-feaf-4a30-a942-35b37ea541d4';

function reply(status = 200, data = null) {
  return {
    status,
    ok: status >= 200 && status < 300,
    async text() { return typeof data === 'string' ? data : data == null ? '' : JSON.stringify(data); },
  };
}
function createClient(response = reply()) {
  const calls = [];
  let answer = response;
  const context = {
    window: {},
    fetch: async (url, options) => {
      calls.push({ url, options });
      return typeof answer === 'function' ? answer(url, options) : answer;
    },
  };
  vm.runInNewContext(source, context, { filename: 'api.js' });
  return {
    api: new context.window.MyMarketplaceAPI('https://example.test/api///'),
    calls,
    setResponse(next) { answer = next; },
    defaults: context.window.MARKETPLACE_DEFAULT_API_URL,
  };
}
const data = (call) => JSON.parse(call.options.body);

// These are true isolated unit tests: no Chrome, Prism, database, or DOM.
test('client normalizes base URL and provides TypeSpec development default', async () => {
  const t = createClient(reply(200, { status: 'ok' }));
  assert.equal(t.defaults, 'http://localhost:9999');
  assert.equal((await t.api.health()).status, 'ok');
  assert.equal(t.calls[0].url, 'https://example.test/api/health');
  assert.equal(t.calls[0].options.credentials, 'omit');
});

test('200 without response body and 204 without response body both produce null', async () => {
  const t = createClient(reply(200, ''));
  assert.equal(await t.api.logout_user(), null);
  t.setResponse(reply(204));
  assert.equal(await t.api.clear_cart(), null);
});

test('login sends JSON with correct credentials mode', async () => {
  const t = createClient(reply(200, { uuid: UUID, username: 'bob_123' }));
  const user = await t.api.login_user('bob_123', 'abcdAB123!@');
  assert.equal(user.username, 'bob_123');
  const req = t.calls[0];
  assert.equal(req.url, 'https://example.test/api/user/login');
  assert.equal(req.options.method, 'POST');
  assert.equal(req.options.credentials, 'include');
  assert.equal(req.options.headers['Content-Type'], 'application/json');
  assert.deepEqual(data(req), { username: 'bob_123', password: 'abcdAB123!@' });
});

test('registration uses the expected endpoint and JSON shape', async () => {
  const t = createClient();
  await t.api.register_user('alice_123', 'abcdAB123!@');
  assert.equal(t.calls[0].url, 'https://example.test/api/user/register');
  assert.deepEqual(data(t.calls[0]), { username: 'alice_123', password: 'abcdAB123!@' });
  assert.equal(t.calls[0].options.credentials, 'include');
});

test('search encodes the query, product detail encodes id', async () => {
  const t = createClient(reply(200, []));
  await t.api.search_product('T-Shirt & more');
  await t.api.get_product(UUID);
  assert.equal(t.calls[0].url, 'https://example.test/api/products/search?q=T-Shirt%20%26%20more');
  assert.equal(t.calls[1].url, `https://example.test/api/products/${UUID}`);
});

test('add_to_cart accepts quantities 1 and 1000 and sends product UUID, not object', async () => {
  const t = createClient(reply(200));
  await t.api.add_to_cart(UUID);
  await t.api.add_to_cart(UUID, 1000);
  assert.equal(t.calls.length, 2);
  for (const call of t.calls) {
    assert.equal(call.url, 'https://example.test/api/cart');
    assert.equal(call.options.method, 'POST');
    assert.equal(call.options.credentials, 'include');
  }
  assert.deepEqual(data(t.calls[0]), { product: UUID, quantity: 1 });
  assert.deepEqual(data(t.calls[1]), { product: UUID, quantity: 1000 });
});

for (const quantity of [0, -1, 1.5, 1001, '2', NaN, Infinity]) {
  test(`add_to_cart rejects invalid quantity ${String(quantity)} before fetching`, () => {
    const t = createClient();
    assert.throws(() => t.api.add_to_cart(UUID, quantity), /Quantity must be a whole number/);
    assert.equal(t.calls.length, 0);
  });
}

test('add_to_cart rejects invalid UUIDv4 before fetching', () => {
  const t = createClient();
  for (const value of ['foo', '', null, '27463fb9-feaf-1a30-a942-35b37ea541d4']) {
    assert.throws(() => t.api.add_to_cart(value, 1), /valid product UUIDv4/);
  }
  assert.equal(t.calls.length, 0);
});

test('cart update, delete, and clear use documented paths and verbs', async () => {
  const t = createClient(reply(200));
  await t.api.edit_cart(3, { quantity: 7 });
  await t.api.delete_cart(3);
  await t.api.clear_cart();
  assert.deepEqual(t.calls.map(c => [c.options.method, c.url]), [
    ['PATCH', 'https://example.test/api/cart?index=3'],
    ['DELETE', 'https://example.test/api/cart?index=3'],
    ['DELETE', 'https://example.test/api/cart/clear'],
  ]);
  assert.deepEqual(data(t.calls[0]), { quantity: 7 });
  for (const call of t.calls) assert.equal(call.options.credentials, 'include');
});

test('edit_user sends required uuid and optional username/password', async () => {
  const t = createClient(reply(200, { uuid: UUID, username: 'new_user' }));
  await t.api.edit_user(UUID, 'new_user', null);
  await t.api.edit_user(UUID, null, 'abcdAB123!@');
  assert.deepEqual(data(t.calls[0]), { uuid: UUID, username: 'new_user' });
  assert.deepEqual(data(t.calls[1]), { uuid: UUID, password: 'abcdAB123!@' });
  assert.deepEqual(t.calls.map(c => c.options.method), ['PATCH', 'PATCH']);
});

test('edit_user prevents an empty update', () => {
  const t = createClient();
  assert.throws(() => t.api.edit_user(UUID, '', ''), /Enter a username or password/);
  assert.equal(t.calls.length, 0);
});

test('delete_user and legacy delete alias use DELETE /user', async () => {
  const t = createClient(reply(200));
  await t.api.delete_user();
  await t.api.delete();
  assert.deepEqual(t.calls.map(c => c.options.method), ['DELETE', 'DELETE']);
  assert.ok(t.calls.every(c => c.url.endsWith('/user')));
});

test('API error preserves HTTP status and server message', async () => {
  const t = createClient(reply(404, { code: 404, message: 'Cart is empty.' }));
  await assert.rejects(t.api.list_cart(), (error) => {
    assert.equal(error.name, 'MarketplaceAPIError');
    assert.equal(error.status, 404);
    assert.equal(error.message, 'Cart is empty.');
    assert.equal(error.details.code, 404);
    return true;
  });
});

test('non-JSON error body becomes readable message', async () => {
  const t = createClient(reply(503, 'Upstream down'));
  await assert.rejects(t.api.health(), (error) => error.status === 503 && error.message === 'Upstream down');
});

test('invalid successful JSON is reported instead of silently ignored', async () => {
  const t = createClient(reply(200, '{broken'));
  await assert.rejects(t.api.list_products(), (error) =>
    error.name === 'MarketplaceAPIError' && error.status === 200 && /invalid JSON/i.test(error.message));
});

test('network failure is wrapped with actionable API error', async () => {
  const t = createClient(() => { throw new TypeError('offline'); });
  await assert.rejects(t.api.health(), (error) =>
    error.name === 'MarketplaceAPIError' && error.status === 0 && /Could not reach the API/.test(error.message));
});
