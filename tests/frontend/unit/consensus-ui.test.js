const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const appSource = fs.readFileSync(path.join(__dirname, '../../../web_classic/app/js/app.js'), 'utf8');
const i18nSource = fs.readFileSync(path.join(__dirname, '../../../web_classic/app/js/i18n.js'), 'utf8');

function functionBlock(name, nextName) {
    const start = appSource.indexOf(`function ${name}(`);
    const end = appSource.indexOf(`function ${nextName}(`, start);
    assert.ok(start >= 0 && end > start, `Unable to extract ${name}`);
    return appSource.slice(start, end);
}

function createContext(language = 'es') {
    const stored = new Map([['trustnews.language', language]]);
    const document = {
        documentElement: {},
        getElementById: () => null,
        querySelectorAll: () => [],
        addEventListener: () => {}
    };
    const context = vm.createContext({
        console,
        document,
        localStorage: {
            getItem: key => stored.get(key) || null,
            setItem: (key, value) => stored.set(key, value)
        },
        CustomEvent: function CustomEvent() {},
    });
    context.window = context;
    context.window.dispatchEvent = () => {};
    vm.runInContext(i18nSource, context);
    vm.runInContext(`
        function t(key, params = {}) { return window.I18N.t(key, params); }
        function safeText(value) {
            return String(value ?? "").replace(/[&<>"']/g, char => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"})[char]);
        }
    `, context);
    vm.runInContext(functionBlock('formatMaxTwoDecimals', 'parseApiTimestamp'), context);
    vm.runInContext(functionBlock('parseApiTimestamp', 'formatDurationMinutesSeconds'), context);
    vm.runInContext(functionBlock('formatWeightPercent', 'evidenceStrategyStatus'), context);
    return context;
}

function result(verdict, decisionStatus, reasonCode, overrides = {}) {
    return {
        verdict,
        decision_status: decisionStatus,
        reason_code: reasonCode,
        distribution: {
            raw_weight: { TRUE: 1, FALSE: 0.5, UNKNOWN: 0.25 },
            decisive_share: { TRUE: 2 / 3, FALSE: 1 / 3 },
            decisive_coverage: 0.4,
            abstention_share: 0.6,
            decision_margin: 1 / 3
        },
        counts: { decisive: 2, abstentions: 1, errors: 0 },
        errors_count: 0,
        ...overrides
    };
}

test('renders TRUE consensus and FALSE weighted majority as weight, never probability', () => {
    const context = createContext('es');
    const consensus = context.decisionPresentation(result('TRUE', 'CONSENSUS', 'ALL_DECISIVE_AGREE_TRUE'));
    const majority = context.decisionPresentation(result('FALSE', 'WEIGHTED_MAJORITY', 'FALSE_WEIGHT_EXCEEDS_TRUE_WEIGHT'));
    const html = context.renderScorePills(result('FALSE', 'WEIGHTED_MAJORITY', 'FALSE_WEIGHT_EXCEEDS_TRUE_WEIGHT'));

    assert.equal(consensus.title, 'Verdadero — consenso de los validadores decisivos');
    assert.equal(majority.title, 'Falso — mayoría ponderada');
    assert.match(majority.explanation, /peso decisivo/);
    assert.match(html, /TRUE · peso 1/);
    assert.doesNotMatch(html.toLowerCase(), /probabilidad|probability|confidence/);
});

test('explains every inconclusive decision in Spanish', () => {
    const context = createContext('es');
    const tie = context.decisionPresentation(result('UNKNOWN', 'NO_CONSENSUS', 'TRUE_FALSE_WEIGHT_TIE'));
    const low = context.decisionPresentation(result('UNKNOWN', 'INSUFFICIENT_EVIDENCE', 'DECISIVE_COVERAGE_TOO_LOW'));
    const none = context.decisionPresentation(result('UNKNOWN', 'NO_VALID_RESPONSES', 'ALL_VALIDATIONS_FAILED'));

    assert.equal(tie.title, 'No concluyente — sin consenso');
    assert.match(tie.explanation, /mismo peso/);
    assert.equal(low.title, 'No concluyente — evidencia insuficiente');
    assert.match(low.explanation, /40 % del peso completado/);
    assert.equal(none.title, 'No concluyente — sin respuestas válidas');
});

test('decision translations are available in English', () => {
    const context = createContext('en');
    const tie = context.decisionPresentation(result('UNKNOWN', 'NO_CONSENSUS', 'TRUE_FALSE_WEIGHT_TIE'));
    const majority = context.decisionPresentation(result('TRUE', 'WEIGHTED_MAJORITY', 'TRUE_WEIGHT_EXCEEDS_FALSE_WEIGHT'));

    assert.equal(tie.title, 'Inconclusive — no consensus');
    assert.equal(tie.explanation, 'TRUE and FALSE have the same weight');
    assert.equal(majority.title, 'True — weighted majority');
    assert.match(majority.explanation, /of decisive weight/);
});

function installSummaryFunction(context) {
    Object.assign(context, {
        getExpectedValidationCount: order => Object.values(order.validations || {}).reduce((n, values) => n + Object.keys(values || {}).length, 0),
        collectOrderAssertions: assertions => assertions || [],
        getAssertionId: (assertion, index) => String(assertion.idAssertion ?? index),
        getValidationLiteral: approval => ({ TRUE: 'True', FALSE: 'False', UNKNOWN: 'Unknown' })[String(approval)] || 'Unknown',
        getEndToEndValidationDuration: () => '',
    });
    vm.runInContext(`
        function isValidationError(validation = {}) { return validation.execution_status === "ERROR"; }
        function completedValidations(validators = {}) { return Object.values(validators).filter(validation => validation?.execution_status === "COMPLETED"); }
        function pluralizeEs(count, singular, plural) { return count + " " + (count === 1 ? singular : plural); }
    `, context);
    vm.runInContext(functionBlock('buildVerificationSummary', 'assertionOutcome'), context);
}

test('API timestamps accept zoned ISO or epoch and reject ambiguous dates', () => {
    const context = createContext('es');

    assert.equal(context.parseApiTimestamp('2026-10-06T14:32:18Z').toISOString(), '2026-10-06T14:32:18.000Z');
    assert.equal(context.parseApiTimestamp('2026-10-06T16:32:18+02:00').toISOString(), '2026-10-06T14:32:18.000Z');
    assert.equal(context.parseApiTimestamp(1791297138).toISOString(), '2026-10-06T14:32:18.000Z');
    assert.equal(context.parseApiTimestamp('04/09/2026 19:16:00'), null);
    assert.equal(context.parseApiTimestamp('2026-10-06T14:32:18'), null);
});

test('summary falls back to current completed validations without weighted results', () => {
    const context = createContext('es');
    installSummaryFunction(context);
    const summary = context.buildVerificationSummary({
        assertions: [{ idAssertion: '1' }],
        validations: {
            1: {
                completed: { execution_status: 'COMPLETED', approval: 'TRUE' },
                failed: { execution_status: 'ERROR', approval: null }
            }
        },
        assertion_results: {}
    });

    assert.equal(summary.confirmedAssertions, 1);
    assert.equal(summary.completedValidations, 2);
    assert.equal(summary.errorValidations, 1);
    assert.equal(summary.validValidations, 1);
});

test('terminal process presentation never labels the result provisional', () => {
    const context = createContext('es');
    context.isTerminalOrderStatus = status => ['VALIDATED', 'VALIDATED_WITH_ERRORS', 'ERROR'].includes(String(status));
    vm.runInContext(functionBlock('buildProcessResultPresentation', 'renderOrderProcess'), context);

    const presentation = context.buildProcessResultPresentation(
        { status: 'VALIDATED_WITH_ERRORS' },
        {
            confirmedAssertions: 0, contradictedAssertions: 0, inconclusiveAssertions: 1,
            noConsensusAssertions: 0, insufficientEvidenceAssertions: 1, noValidResponsesAssertions: 0,
            validValidations: 2, errorValidations: 1, pendingValidations: 0
        }
    );

    assert.equal(presentation.terminal, true);
    assert.equal(presentation.title, 'Resultado final');
    assert.equal(presentation.badge, 'Finalizado con incidencias');
    assert.doesNotMatch(`${presentation.title} ${presentation.badge} ${presentation.notice}`, /provisional/i);

    const failed = context.buildProcessResultPresentation(
        { status: 'ERROR' },
        {
            confirmedAssertions: 0, contradictedAssertions: 0, inconclusiveAssertions: 0,
            noConsensusAssertions: 0, insufficientEvidenceAssertions: 0, noValidResponsesAssertions: 0,
            validValidations: 0, errorValidations: 0, pendingValidations: 0
        }
    );
    assert.equal(failed.label, 'Sin decisión disponible');
    assert.equal(failed.badge, 'Finalizado con incidencias');
});

test('FALSE plus UNKNOWN is PARTIALLY_VERIFIED, never an absolute disproved document', () => {
    const context = createContext('es');
    installSummaryFunction(context);
    const summary = context.buildVerificationSummary({
        assertions: [{ idAssertion: '1' }, { idAssertion: '2' }],
        validations: {
            1: { a: { execution_status: 'COMPLETED', approval: 'FALSE' } },
            2: { b: { execution_status: 'COMPLETED', approval: 'UNKNOWN' } }
        },
        assertion_results: {
            1: result('FALSE', 'CONSENSUS', 'ALL_DECISIVE_AGREE_FALSE'),
            2: result('UNKNOWN', 'INSUFFICIENT_EVIDENCE', 'NO_DECISIVE_VALIDATIONS')
        }
    });

    assert.equal(summary.documentStatus, 'PARTIALLY_VERIFIED');
    assert.equal(summary.statusKey, 'partial');
    assert.equal(summary.contradictedAssertions, 1);
    assert.equal(summary.insufficientEvidenceAssertions, 1);
    assert.doesNotMatch(summary.conclusionText, /queda desmentida/i);
});

test('multi-assertion summary preserves no-consensus and insufficiency distribution', () => {
    const context = createContext('en');
    installSummaryFunction(context);
    const validations = {};
    const assertionResults = {};
    const specs = [
        ['TRUE', 'CONSENSUS'], ['TRUE', 'CONSENSUS'], ['TRUE', 'WEIGHTED_MAJORITY'],
        ['FALSE', 'CONSENSUS'], ['UNKNOWN', 'NO_CONSENSUS'], ['UNKNOWN', 'INSUFFICIENT_EVIDENCE']
    ];
    specs.forEach(([verdict, status], index) => {
        const id = String(index + 1);
        validations[id] = { [`v${id}`]: { execution_status: 'COMPLETED', approval: verdict } };
        assertionResults[id] = result(verdict, status, status === 'NO_CONSENSUS' ? 'TRUE_FALSE_WEIGHT_TIE' : 'NO_DECISIVE_VALIDATIONS');
    });
    const summary = context.buildVerificationSummary({
        assertions: specs.map((_, index) => ({ idAssertion: String(index + 1) })),
        validations,
        assertion_results: assertionResults
    });

    assert.equal(summary.documentStatus, 'MIXED');
    assert.deepEqual(
        [summary.confirmedAssertions, summary.contradictedAssertions, summary.noConsensusAssertions, summary.insufficientEvidenceAssertions],
        [3, 1, 1, 1]
    );
    assert.match(summary.conclusionText, /1 without consensus/);
    assert.match(summary.conclusionText, /1 with insufficient evidence/);
});
