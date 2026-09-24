import importlib.util
import json
import pathlib
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("llm_benchmark", ROOT / "scripts/llm-benchmark.py")
benchmark = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(benchmark)


class LLMBenchmarkTests(unittest.TestCase):
    def test_profile_rejects_non_openrouter_provider(self):
        profile = {
            "schema_version": 1,
            "id": "invalid",
            "components": {"generate-asertions": {"provider": "gemini", "model": "x"}},
        }
        with self.assertRaises(benchmark.BenchmarkError):
            benchmark.validate_profile(profile)

    def test_current_marker_requires_an_effective_openrouter_model(self):
        marker = "$" + "current"
        profile = {
            "schema_version": 1,
            "id": "current",
            "components": {"generate-asertions": {"provider": "openrouter", "model": marker}},
            "validators": [],
        }
        manager = benchmark.ConfigurationManager(None)
        snapshot = {
            "components": {
                "generate-asertions": {
                    "provider": "openrouter", "model": "vendor/model",
                    "temperature": 0, "config_version": 1,
                },
            },
            "validators": {},
        }

        resolved = manager.resolve_profile(profile, snapshot)
        self.assertEqual(resolved["components"]["generate-asertions"]["model"], "vendor/model")

        snapshot["components"]["generate-asertions"]["provider"] = "gemini"
        with self.assertRaises(benchmark.BenchmarkError):
            manager.resolve_profile(profile, snapshot)

    def test_scores_extraction_and_verdicts_against_canonical_assertions(self):
        case = {
            "schema_version": 1,
            "id": "case",
            "news": "sample",
            "match_threshold": 0.5,
            "assertions": [
                {
                    "id": "A", "expected_verdict": "TRUE", "category_ids": [5],
                    "required_terms": ["Suecia", "vacunación", "infantil"],
                },
                {
                    "id": "B", "expected_verdict": "FALSE", "category_ids": [8],
                    "required_terms": ["Italia", "turistas", "centros", "históricos"],
                },
            ],
        }
        order = {
            "assertions": [
                {"idAssertion": "1", "text": "Suecia amplía la vacunación infantil", "categoryId": 5},
                {"idAssertion": "2", "text": "Italia prohíbe turistas en centros históricos", "categoryId": 8},
            ],
            "assertion_results": {
                "1": {"verdict": "TRUE"},
                "2": {"verdict": "FALSE"},
            },
            "validations": {
                "1": {"v1": {
                    "approval": 1, "execution_status": "COMPLETED",
                    "validator_type": "LLM_MEMORY_VALIDATION", "response_time_seconds": 1.2,
                }},
                "2": {"v1": {
                    "approval": 2, "execution_status": "COMPLETED",
                    "validator_type": "LLM_MEMORY_VALIDATION", "response_time_seconds": 1.8,
                }},
            },
        }

        score = benchmark.score_order(case, order)

        self.assertEqual(score["metrics"]["assertion_coverage"], 1)
        self.assertEqual(score["metrics"]["verdict_accuracy"], 1)
        self.assertEqual(score["validators"]["v1"]["accuracy"], 1)
        self.assertEqual(score["quality_score"], 100)

    def test_costs_keep_sample_and_normalized_five_assertion_totals(self):
        pricing = {
            "generated_at": "2026-01-01T00:00:00Z",
            "estimated_news_costs_usd": {"current": 0.56},
            "deployment_recommendations": [
                {
                    "target_id": "generate-asertions", "target_kind": "component",
                    "current_provider": "openrouter", "current_model": "generator",
                    "estimated_current_cost_usd": 0.01,
                },
                {
                    "target_id": "validator", "target_kind": "validator",
                    "workload_key": "memory", "current_provider": "openrouter",
                    "current_model": "validator", "estimated_current_cost_usd": 0.11,
                },
            ],
        }

        costs = benchmark.collect_costs(pricing, 4)

        self.assertAlmostEqual(costs["sample_total_usd"], 0.45)
        self.assertAlmostEqual(costs["normalized_5_assertions_total_usd"], 0.56)
        self.assertTrue(costs["complete"])

        incomplete = benchmark.collect_costs(pricing, 4, {"generate-asertions", "missing"})
        self.assertFalse(incomplete["complete"])
        self.assertEqual(incomplete["missing_targets"], ["missing"])

    def test_generates_exact_profiles_under_budget_and_deduplicates(self):
        snapshot = {
            "captured_at": "2026-01-01T00:00:00Z",
            "components": {
                "generate-asertions": {
                    "provider": "openrouter", "model": "vendor/current-generator",
                    "temperature": 0, "config_version": 1,
                },
            },
            "validators": {
                "validator-1": {
                    "provider": "openrouter", "model": "vendor/current-validator",
                    "temperature": 0.2, "config_version": 1,
                    "validator_type": "LLM_MEMORY_VALIDATION", "strategy": None,
                },
            },
        }
        pricing = {
            "estimated_news_costs_usd": {
                "premium": 0.19, "similar": 0.19, "budget": 0.08,
            },
            "deployment_recommendations": [
                {
                    "target_kind": "component", "target_id": "generate-asertions",
                    "current_provider": "openrouter", "current_model": "vendor/current-generator",
                    "estimated_current_cost_usd": 0.01,
                    "options": [
                        {"tier": "premium", "model": "vendor/premium-generator"},
                        {"tier": "similar", "model": "vendor/premium-generator"},
                        {"tier": "budget", "model": "vendor/budget-generator"},
                    ],
                },
                {
                    "target_kind": "validator", "target_id": "validator-1",
                    "current_provider": "openrouter", "current_model": "vendor/current-validator",
                    "estimated_current_cost_usd": 0.02,
                    "options": [
                        {"tier": "premium", "model": "vendor/premium-validator"},
                        {"tier": "similar", "model": "vendor/premium-validator"},
                        {"tier": "budget", "model": "vendor/budget-validator"},
                    ],
                },
            ],
        }

        profiles, discarded = benchmark.generated_profiles(snapshot, pricing, 0.20, 0.19)

        self.assertEqual([item["id"] for item in profiles], ["premium-safe", "budget-safe"])
        self.assertEqual(profiles[0]["validators"][0]["selector"], {"id": "validator-1"})
        self.assertEqual(profiles[0]["validators"][0]["temperature"], 0.2)
        self.assertEqual(discarded[0]["reason"], "duplicate_configuration")
        self.assertEqual(discarded[0]["duplicate_of"], "premium-safe")
        self.assertTrue(all(
            item["generation"]["estimated_news_cost_usd"] <= 0.19 for item in profiles
        ))

    def test_profile_generation_rejects_incomplete_target_costs(self):
        snapshot = {
            "components": {
                "generate-asertions": {"provider": "openrouter", "model": "vendor/model"},
            },
            "validators": {
                "missing-validator": {"provider": "openrouter", "model": "vendor/model"},
            },
        }
        pricing = {
            "estimated_news_costs_usd": {"budget": 0.01},
            "deployment_recommendations": [{
                "target_kind": "component", "target_id": "generate-asertions",
                "current_provider": "openrouter", "current_model": "vendor/model",
                "estimated_current_cost_usd": 0.01, "options": [],
            }],
        }

        with self.assertRaisesRegex(benchmark.BenchmarkError, "missing-validator"):
            benchmark.generated_profiles(snapshot, pricing, 0.10, 0.095)

    def test_profile_plan_resolves_relative_paths_and_checks_hash(self):
        profile = {
            "schema_version": 1, "id": "generated",
            "components": {"generate-asertions": {
                "provider": "openrouter", "model": "vendor/model",
            }},
        }
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory)
            profile_path = root / "profiles/generated.json"
            profile_path.parent.mkdir()
            profile_path.write_text(json.dumps(profile), encoding="utf-8")
            plan_path = root / "plan.json"
            plan = {
                "schema_version": 1, "plan_id": "plan",
                "requested_max_news_cost_usd": 0.20,
                "effective_max_news_cost_usd": 0.19,
                "profiles": [{
                    "path": "profiles/generated.json",
                    "sha256": benchmark.sha256_text(benchmark.canonical_json(profile)),
                }],
            }
            plan_path.write_text(json.dumps(plan), encoding="utf-8")

            paths, loaded = benchmark.load_profile_plan(plan_path)
            self.assertEqual(paths, [profile_path.resolve()])
            self.assertEqual(loaded["plan_id"], "plan")

            profile["id"] = "tampered"
            profile_path.write_text(json.dumps(profile), encoding="utf-8")
            with self.assertRaisesRegex(benchmark.BenchmarkError, "hash"):
                benchmark.load_profile_plan(plan_path)

    def test_sqlite_history_is_append_only_and_comparable(self):
        with tempfile.TemporaryDirectory() as directory:
            database = pathlib.Path(directory) / "history.sqlite"
            history = benchmark.History(database)
            manifest = {
                "batch_id": "batch", "started_at": "2026-01-01T00:00:00Z",
                "case": {"id": "case"}, "git": {"commit": "abc", "dirty": False},
                "artifacts_dir": directory,
            }
            history.start_batch(manifest)
            for run_id, quality, cost in (("base", 70.0, 0.2), ("candidate", 80.0, 0.15)):
                history.save_run({
                    "run_id": run_id, "batch_id": "batch", "profile_id": run_id,
                    "repetition": 1, "started_at": "2026-01-01T00:00:00Z",
                    "finished_at": "2026-01-01T00:01:00Z", "status": "PASS",
                    "quality_score": quality, "score": {
                        "quality_score": quality,
                        "metrics": {"verdict_accuracy": quality / 100},
                        "assertions": [],
                    },
                    "costs": {
                        "sample_total_usd": cost,
                        "normalized_5_assertions_total_usd": cost,
                        "modules": [],
                    },
                    "duration_seconds": 60, "resolved_profile": {},
                })
            result = benchmark.comparison(history.get_run("base"), history.get_run("candidate"))
            history.close()

        self.assertEqual(result["delta"]["quality_score"], 10)
        self.assertAlmostEqual(result["delta"]["sample_cost_usd"], -0.05)


if __name__ == "__main__":
    unittest.main()
