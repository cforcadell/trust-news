const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const source = fs.readFileSync(path.join(__dirname, '../app/js/app.js'), 'utf8');
const context = vm.createContext({});
const start = source.indexOf('function assertionStatusClass(');
assert.ok(start >= 0, 'Missing function assertionStatusClass');
const end = source.indexOf('\n}', start) + 2;
vm.runInContext(source.slice(start, end), context);

test('UNKNOWN aggregate result is orange even when TRUE outnumbers FALSE', () => {
    const status = context.assertionStatusClass({ winner: 'UNKNOWN' }, 1, 0, 2, 0);
    assert.equal(status, 'unknown');
});

test('falls back to completed vote counts when no aggregate result exists', () => {
    assert.equal(context.assertionStatusClass(null, 2, 1, 0, 0), 'true');
    assert.equal(context.assertionStatusClass(null, 1, 2, 0, 0), 'false');
    assert.equal(context.assertionStatusClass(null, 0, 0, 2, 0), 'unknown');
});
