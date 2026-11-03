const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const source = fs.readFileSync(path.join(__dirname, '../../../web_classic/app/js/app.js'), 'utf8');
const start = source.indexOf('function getAssertionId(');
const end = source.indexOf('function assertionMatchesId(', start);

assert.ok(start >= 0 && end > start, 'Unable to extract assertion collection helpers');

function collect(assertions, orderData) {
    const context = vm.createContext({});
    vm.runInContext(source.slice(start, end), context);
    return context.collectOrderAssertions(assertions, orderData);
}

test('deduplicates the UI projection and canonical assertion document by assertion ID', () => {
    const text = 'En 2025 Catalunya tiene una población de más de 8 millones de habitantes.';
    const assertions = [{ idAssertion: '1', text, categoryId: 10 }];
    const orderData = {
        assertions,
        document: {
            assertions: [{ assertion_id: 1, assertion_index: 0, text, categoryId: 10 }]
        }
    };

    const collected = collect(assertions, orderData);

    assert.equal(collected.length, 1);
    assert.equal(collected[0].idAssertion, '1');
});

test('keeps assertions with distinct explicit IDs even when their text matches', () => {
    const collected = collect([
        { idAssertion: '1', text: 'Texto repetido' },
        { idAssertion: '2', text: 'Texto repetido' }
    ]);

    assert.equal(collected.length, 2);
});
