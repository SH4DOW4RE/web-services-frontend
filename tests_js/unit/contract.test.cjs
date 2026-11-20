'use strict';
const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const html = fs.readFileSync(path.join(__dirname, '../../frontend/index.html'), 'utf8');
const openapi = fs.readFileSync(path.join(__dirname, '../../schema/openapi.yaml'), 'utf8');

function htmlPattern(id) {
  const element = html.match(new RegExp(`<input\\b[^>]*\\bid="${id}"[^>]*>`, 's'));
  assert.ok(element, `Missing input #${id}`);
  const found = element[0].match(/\bpattern="([^"]+)"/);
  assert.ok(found, `Input #${id} needs pattern validation`);
  return found[1];
}

// Match a component schema's pattern without adding a YAML parser dependency.
// Expected generated OpenAPI layout: components.schemas.Username/Password.pattern.
function schemaPattern(name) {
  const lines = openapi.split(/\r?\n/);
  const header = new RegExp(`^ {4}${name}:\\s*$`);
  const start = lines.findIndex((line) => header.test(line));
  assert.ok(start >= 0, `OpenAPI schema ${name} not found`);

  for (let index = start + 1; index < lines.length; index++) {
    const line = lines[index];
    if (/^ {4}\S/.test(line) || /^ {2}\S/.test(line)) break;
    const match = line.match(/^\s+pattern:\s*(.*?)\s*$/);
    if (match) {
      const raw = match[1];
      return raw.replace(/^(['"])(.*)\1$/, '$2');
    }
  }
  assert.fail(`OpenAPI schema ${name} has no pattern`);
}

function matchesHtml(id, sample) {
  // HTML input pattern has implicit full-string matching.
  return new RegExp(`^(?:${htmlPattern(id)})$`).test(sample);
}

test('username input patterns match OpenAPI Username schema', () => {
  const spec = new RegExp(schemaPattern('Username'));
  const samples = ['bob_123', 'abcde', 'a1234', 'Abcde', 'abc', '1abcd', 'bad-name', 'abcdefghijklmnopq'];
  for (const id of ['auth-username', 'new-username']) {
    for (const value of samples) {
      assert.equal(matchesHtml(id, value), spec.test(value), `${id}: ${value}`);
    }
  }
});

test('password input patterns match OpenAPI Password schema', () => {
  const spec = new RegExp(schemaPattern('Password'));
  const samples = ['abcdAB123!@', 'abcdAB12!@', 'abcdAB123', 'ABCDabcd123!@', 'abcdAB123!!', 'abcdAB123!@$'];
  for (const id of ['auth-password', 'new-password']) {
    for (const value of samples) {
      assert.equal(matchesHtml(id, value), spec.test(value), `${id}: ${value}`);
    }
  }
});

test('UI documents no checkout and provides cart quantity controls', () => {
  assert.ok(html.includes('id="cart-summary"'));
  assert.ok(html.includes('id="cart-count"'));
  assert.ok(html.includes('id="product-card-template"'));
  assert.ok(!html.includes('id="checkout-button"'), 'Do not imply undocumented checkout endpoint exists');
});
