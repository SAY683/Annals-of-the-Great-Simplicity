'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const { safeNextPath, parseCookies } = require('./gate_helpers');

test('safeNextPath keeps local paths', () => {
  assert.equal(safeNextPath('/api/status?x=1'), '/api/status?x=1');
});

test('safeNextPath rejects open redirects and control characters', () => {
  assert.equal(safeNextPath('https://evil.example/'), '/');
  assert.equal(safeNextPath('//evil.example/'), '/');
  assert.equal(safeNextPath('/ok\r\nLocation: https://evil.example'), '/');
  assert.equal(safeNextPath('\\\\evil.example'), '/');
});

test('parseCookies ignores malformed percent encoding', () => {
  assert.deepEqual(parseCookies('a=1; bad=%E0%A4%A; ok=hello%20world'), {
    a: '1',
    ok: 'hello world',
  });
});