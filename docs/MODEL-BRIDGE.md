# Model Bridge comparisons

Orchestrator evaluates coding-model workers under the same pinned Git commit, with independent tests and structured evidence. It is a deliberately narrow lab feature, not a production model router.

Core command:

~~~sh
orchestrator compare /absolute/path/to/sanitized-clone /absolute/path/to/suite.yaml --output /absolute/path/to/new-report-folder --confirm-sanitized-lab --allow-edit
~~~

Add --allow-cloud only when the manifest contains hosted provider targets and you expressly authorize the provider calls and any charges. If absent, cloud targets are rejected. A comparison manifest has version: 1; name; repeats; timeout_seconds; verification_timeout_seconds; scenarios with id, prompt, mode (inspect/patch) and verification commands; targets with id, kind (local/cloud) and model ID.

Local worker: existing ollama-local/OpenCode adapter, with an explicitly selected model and no automatic cloud fallback. Cloud worker: OpenCode with one exact provider/model and provider allowlist. The core never imports the private SeaCommons package.

Each model/scenario/repetition runs in a fresh detached Git worktree based on the source SHA. Experiments are sequential, and order rotates to reduce warm-cache bias. Patch tasks require a failing baseline test and independent passing tests after an actual code change. An initially passing baseline gets INVALID_BASELINE, and inspect-only tasks receive INSPECT_ONLY, never a fake PASS.

Results: comparison.json, comparison.md and per-trial tracked Git diffs. Pairwise records cover local-local, local-cloud and cloud-cloud; missing provider costs and hardware metrics remain unknown, not zero. The output folder must be outside the source Git checkout.

Security: --confirm-sanitized-lab is mandatory and must be a truthful confirmation of a disposable, credential-free repository. Patch tasks require --allow-edit. Test commands from a suite run as host shell commands, and OpenCode agents may still launch processes if provider permissions fail to enforce boundaries: this is NOT an operating-system sandbox. Use an OS user or container with no access to production secrets or infrastructure. Model pinning alone does not prove network isolation.

No automatic changes to global provider policy, no production deploy, merge or push. A passing microbenchmark does not establish broader model safety, reliability or usefulness.

For a real SeaCommons AIS case study, the private repository supplies an isolated seed tool, manifests and Windows instructions at docs/MODEL-BRIDGE.md.
