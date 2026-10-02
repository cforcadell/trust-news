# Test data

Test inputs and generated output are grouped by test type:

```text
tests/data/<type>/
  resources/   # versioned datasets, cases, profiles, and fixtures
  artifacts/   # generated local output, ignored by Git, organized by run ID
```

`evaluation`, `benchmark`, and `frontend-e2e` use this structure directly.
`historical-stats` retains imported samples in the same split. `pytest/artifacts/cache` holds the local pytest cache and is not test evidence.

Resources are immutable test inputs: introduce a new version rather than replacing a reviewed resource. Artifacts are append-only run output. Do not overwrite a campaign, batch, or run directory; retain any artifact needed as evidence outside Git with its commit, input hashes, environment, and date.
