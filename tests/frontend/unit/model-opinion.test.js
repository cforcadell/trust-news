const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const source = fs.readFileSync(path.join(__dirname, '../app/js/app.js'), 'utf8');
const context = vm.createContext({ t: key => key });
for (const name of ['escapeHTML', 'safeText', 'evidenceValidationResult', 'unverifiedModelOpinion', 'renderModelOpinionAudit']) {
    const start = source.indexOf(`function ${name}(`);
    vm.runInContext(source.slice(start, source.indexOf('\n}', start) + 2), context);
}
test('only unsupported documentary decisive opinions get the separate presentation', () => {
    const audit = { basis: 'RETRIEVED_EVIDENCE', original_verdict: 'TRUE', effective_verdict: 'UNKNOWN' };
    assert.ok(context.unverifiedModelOpinion({ payload: { evidence_validation: audit } }));
    for (const override of [{ original_verdict: 'UNKNOWN' }, { effective_verdict: 'TRUE' }, { basis: 'MODEL_KNOWLEDGE' }]) {
        assert.equal(context.unverifiedModelOpinion({ evidence_validation: { ...audit, ...override } }), null);
    }
});
test('audit shows full provided text and escapes model-controlled content', () => {
    const text = 'Texto exacto '.repeat(100) + '<script>alert(1)</script>';
    const html = context.renderModelOpinionAudit({}, {
        provided_evidence_text: text, original_description: '<img src=x onerror=alert(1)>',
        claimed_evidence: [{ evidence_text: '<svg onload=alert(1)>' }],
        issues: [{ code: 'EVIDENCE_TEXT_NOT_RETRIEVED', source_id: '<script>' }]
    });
    assert.ok(html.includes(context.safeText(text)));
    assert.ok(html.includes('ui.opinionExcluded'));
    assert.doesNotMatch(html, /<script>|<img |<svg /);
});
test('legacy records explicitly disclose missing audit data', () => {
    assert.ok(context.renderModelOpinionAudit({}, {}).includes('ui.auditNotRecorded'));
});
