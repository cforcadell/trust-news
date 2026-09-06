const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

// Exercise the actual rendering functions without booting the application.
const source = fs.readFileSync(path.join(__dirname, '../app/js/app.js'), 'utf8');
const context = vm.createContext({ URL, t: () => 'Evidencias' });
for (const name of ['escapeHTML', 'safeText', 'compactText', 'validationEvidenceItems',
    'isGenericEvidenceLabel', 'evidenceUrlHost', 'safeEvidenceUrl',
    'firstEvidenceContextText', 'evidenceDisplayTitle', 'evidenceDecisionText',
    'evidenceSupportsLabel', 'renderEvidenceLinks']) {
    const start = source.indexOf(`function ${name}(`);
    assert.ok(start >= 0, `Missing function ${name}`);
    const end = source.indexOf('\n}', start) + 2;
    vm.runInContext(source.slice(start, end), context);
}

for (const url of ['javascript:alert(1)', 'data:text/html,<script>alert(1)</script>',
    'file:///tmp/test', '//example.test', 'https://[invalid', 'https://user@',
    'https://exa mple.com', 'https://example.test:invalid', 'https://example.test:99999',
    'https:///example.test', 'https://exa\nmple.test', 'https://example.test\\evil',
    'https://%20.test']) {
    test(`renders unsafe URL as inert text: ${JSON.stringify(url)}`, () => {
        for (const key of ['url', 'source_url', 'url_text', 'source_url_text']) {
            const html = context.renderEvidenceLinks({ sources: [{ [key]: url, title: '<img src=x onerror=alert(1)>', quote: 'Fragmento' }] });
            assert.doesNotMatch(html, /<a\b|<script\b|<img\b/);
            assert.ok(html.includes(context.safeText(url)));
            assert.ok(html.includes('Fragmento'));
        }
    });
}

test('HTTP(S) sources remain escaped clickable links', () => {
    for (const url of ['http://example.test/article', 'https://example.test/?a=1&b=2', 'https://[::1]:8443/article']) {
        const html = context.renderEvidenceLinks({ evidence_used: [{ source_url: url, title: 'Fuente' }] });
        assert.ok(html.includes(`href="${context.safeText(new URL(url).href)}"`));
        assert.ok(html.includes('rel="noopener noreferrer"'));
    }
});

test('server display-only fields never become links, even with an HTTP URL', () => {
    const html = context.renderEvidenceLinks({ sources: [{ url_text: 'https://example.test' }] });
    assert.doesNotMatch(html, /<a\b/);
    assert.ok(html.includes('https://example.test'));
});
