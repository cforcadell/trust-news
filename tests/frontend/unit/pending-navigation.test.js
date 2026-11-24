const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const source = fs.readFileSync(path.join(__dirname, '../../../web_classic/app/js/app.js'), 'utf8');
function contextFor(names, stubs = {}) {
    const context = vm.createContext(stubs);
    for (const name of names) {
        let start = source.indexOf(`function ${name}(`);
        if (source.slice(start - 6, start) === 'async ') start -= 6;
        vm.runInContext(source.slice(start, source.indexOf('\n}', start) + 2), context);
    }
    return context;
}
test('waiting for responses is pending; a terminal failure is still an error', () => {
    const context = contextFor(['isTerminalOrderStatus', 'orderValidationPending', 'assertionOutcome'], {
        getAssertionResult: order => order.result,
        completedValidations: () => [], isValidationError: () => false
    });
    const result = { verdict: 'UNKNOWN', decision_status: 'NO_VALID_RESPONSES' };
    assert.equal(context.assertionOutcome({ status: 'VALIDATION_PENDING', result }, '1'), 'pending');
    assert.equal(context.assertionOutcome({ status: 'VALIDATION_PENDING' }, '1'), 'pending');
    assert.equal(context.assertionOutcome({ status: 'VALIDATED_WITH_ERRORS', result }, '1'), 'error');
    assert.equal(context.assertionOutcome({ status: 'VALIDATION_PENDING', result: { verdict: 'TRUE' } }, '1'), 'confirmed');
});
test('switching tabs reads the latest evidence and global order state', () => {
    let rendered;
    const context = contextFor(['renderCurrentOrderTab'], {
        currentOrderData: { assertions: [], validations: {} }, currentOrderEvents: [],
        collectOrderAssertions: assertions => assertions,
        renderTabContent: (...args) => { rendered = args; }
    });
    context.renderCurrentOrderTab('evidence');
    const latest = { assertions: ['new assertion'], validations: { 1: { worker: { approval: true } } } };
    context.currentOrderData = latest;
    context.renderCurrentOrderTab('evidence');
    assert.equal(rendered[1], latest.validations);
    assert.equal(rendered[3], latest);
});
test('polling selects Process once, preserves navigation, and returns there at timeout', async () => {
    let options;
    const activated = [];
    const session = { startedAt: Date.now(), followProcess: true, consecutiveErrors: 0 };
    const context = contextFor(['orderPollingDurationMs', 'currentPollingDurationMs', 'runOrderPollingCycle'], {
        Date, AbortController, POLLING_DURATION: 300000, POLLING_INTERVAL: 3000,
        POLLING_REQUEST_TIMEOUT_MS: 15000, activeOrderPollingSession: session,
        currentOrderData: { status: 'VALIDATION_PENDING' },
        window: { setTimeout: () => 1, clearTimeout: () => {} },
        renderOrderPollingState: () => {}, isTerminalOrderStatus: () => false,
        loadOrderById: async (id, cleanup, opts) => { options = opts; return { ok: true, data: { status: 'VALIDATION_PENDING' } }; },
        stopOrderPolling: () => { session.stopped = true; },
        activateOrderTab: key => activated.push(key), alertMessage: () => {}, t: key => key
    });
    await context.runOrderPollingCycle(session);
    assert.equal(options.preferredTabKey, 'process');
    await context.runOrderPollingCycle(session);
    assert.equal(options.preferredTabKey, null);
    session.startedAt = Date.now() - 300001;
    await context.runOrderPollingCycle(session);
    assert.deepEqual(activated, ['process']);
});

test('terminal polling awaits a clean final render before activating Summary', async () => {
    const calls = [];
    const activated = [];
    const session = { startedAt: Date.now(), followProcess: true, consecutiveErrors: 0, stopped: false };
    const context = contextFor(['orderPollingDurationMs', 'currentPollingDurationMs', 'runOrderPollingCycle'], {
        Date, AbortController, POLLING_DURATION: 300000, POLLING_INTERVAL: 3000,
        POLLING_REQUEST_TIMEOUT_MS: 15000, activeOrderPollingSession: session,
        currentOrderData: { status: 'VALIDATION_PENDING' },
        window: { setTimeout: () => 1, clearTimeout: () => {} },
        renderOrderPollingState: () => {}, isTerminalOrderStatus: status => status === 'VALIDATED',
        loadOrderById: async (id, cleanup, opts) => {
            calls.push({ cleanup, preferredTabKey: opts.preferredTabKey });
            return { ok: true, data: { status: 'VALIDATED' } };
        },
        stopOrderPolling: () => { session.stopped = true; },
        activateOrderTab: key => activated.push(key), alertMessage: () => {}, t: key => key,
        console: { log: () => {} }
    });

    await context.runOrderPollingCycle(session);

    assert.deepEqual(calls, [
        { cleanup: false, preferredTabKey: 'process' },
        { cleanup: true, preferredTabKey: 'summary' }
    ]);
    assert.deepEqual(activated, ['summary']);
});

test('order polling lasts through the configured automatic completion deadline', () => {
    const context = contextFor(['orderPollingDurationMs'], {
        POLLING_DURATION: 300000,
        parseApiTimestamp: value => new Date(value)
    });
    assert.equal(context.orderPollingDurationMs({ validation_deadline_minutes: 30 }), 35 * 60 * 1000);
    assert.equal(context.orderPollingDurationMs({ validation_deadline_minutes: 0 }), 5 * 60 * 1000);
    assert.equal(context.orderPollingDurationMs({ validation_deadline_minutes: 30, validation_deadline_at: '2026-11-21T11:40:00Z' }, Date.parse('2026-11-21T11:00:00Z')), 41 * 60 * 1000);
});

test('polling uses the publish policy before the first order detail arrives', () => {
    const context = contextFor(['orderPollingDurationMs', 'currentPollingDurationMs'], {
        POLLING_DURATION: 300000, currentOrderData: {}, parseApiTimestamp: value => new Date(value)
    });
    const session = { startedAt: Date.parse('2026-11-21T11:00:00Z'), deadlineMinutes: 30 };
    assert.equal(context.currentPollingDurationMs(session), 35 * 60 * 1000);
    context.currentOrderData = { validation_deadline_minutes: 30, validation_deadline_at: '2026-11-21T11:40:00Z' };
    assert.equal(context.currentPollingDurationMs(session), 41 * 60 * 1000);
});
