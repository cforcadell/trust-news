const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const source = fs.readFileSync(path.join(__dirname, '../app/js/app.js'), 'utf8');
const context = vm.createContext({});
const constantStart = source.indexOf('const LLM_NEWS_ASSERTION_COUNT');
const functionsEnd = source.indexOf('\nfunction renderLLMNewsCost', constantStart);
vm.runInContext(`${source.slice(constantStart, functionsEnd)}
this.estimateLLMNewsCost = estimateLLMNewsCost;
this.parseLLMNewsBudget = parseLLMNewsBudget;
this.enforceLLMRecommendationBudget = enforceLLMRecommendationBudget;`, context);

test('estimates a news item with five validations per validator and local RAG routing', () => {
    const deployed = [
        { target_id: 'generate-asertions', target_kind: 'component', estimated_current_cost_usd: 0.01, options: [{ tier: 'premium', estimated_cost_usd: 0.02 }] },
        { target_id: 'source-router', target_kind: 'component', estimated_current_cost_usd: 0.001, options: [{ tier: 'premium', estimated_cost_usd: 0.002 }] },
        { target_id: 'rag-validator', target_kind: 'validator', workload_key: 'ragLocal', estimated_current_cost_usd: 0.1, options: [{ tier: 'premium', estimated_cost_usd: 0.2 }] },
        { target_id: 'search-validator', target_kind: 'validator', workload_key: 'search', estimated_current_cost_usd: 0.05, options: [] },
    ];

    assert.equal(context.estimateLLMNewsCost(deployed), 0.765);
    assert.equal(context.estimateLLMNewsCost(deployed, 'premium'), 1.28);
});

test('does not claim a total when a contributing model has no price', () => {
    const deployed = [{ target_id: 'validator', target_kind: 'validator', estimated_current_cost_usd: null, options: [] }];
    assert.equal(context.estimateLLMNewsCost(deployed), null);
});

test('accepts localized decimal budgets', () => {
    assert.equal(context.parseLLMNewsBudget('0,05'), 0.05);
    assert.equal(context.parseLLMNewsBudget('1.234,56'), 1234.56);
    assert.equal(context.parseLLMNewsBudget('1,234.56'), 1234.56);
    assert.equal(context.parseLLMNewsBudget('0'), null);
});

test('removes every tier combination that exceeds the echoed global budget', () => {
    const payload = {
        max_news_cost_usd: 0.5,
        estimated_news_costs_usd: {premium: 9},
        deployment_recommendations: [
            {
                target_id: 'generate-asertions', target_kind: 'component',
                estimated_current_cost_usd: 0.01,
                options: [{tier: 'premium', estimated_cost_usd: 0.02}],
            },
            {
                target_id: 'validator', target_kind: 'validator',
                estimated_current_cost_usd: 0.02,
                options: [{tier: 'premium', estimated_cost_usd: 0.2}],
            },
        ],
    };

    const enforced = context.enforceLLMRecommendationBudget(payload);

    assert.equal(enforced.estimated_news_costs_usd.premium, 0.11);
    assert.equal(
        enforced.deployment_recommendations.some(item =>
            item.options.some(option => option.tier === 'premium')
        ),
        false,
    );
});
