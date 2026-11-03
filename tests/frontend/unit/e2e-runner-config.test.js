const { test } = require('node:test');
const assert = require('node:assert/strict');
const path = require('node:path');
const { spawnSync } = require('node:child_process');

test('E2E runner fails before opening a browser when credentials are absent', () => {
    const runner = path.join(__dirname, '..', 'e2e', 'ui-smoke-test.js');
    const environment = { ...process.env };
    delete environment.ASSERMETRY_USERNAME;
    delete environment.ASSERMETRY_PASSWORD;

    const result = spawnSync(process.execPath, [runner], {
        env: environment,
        encoding: 'utf8'
    });

    assert.notEqual(result.status, 0);
    assert.match(`${result.stdout}\n${result.stderr}`, /Faltan ASSERMETRY_USERNAME y\/o ASSERMETRY_PASSWORD/);
    assert.doesNotMatch(`${result.stdout}\n${result.stderr}`, /SCENARIO_RESULT .* PASS/);
});
