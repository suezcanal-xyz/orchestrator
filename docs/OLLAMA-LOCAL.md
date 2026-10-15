# Local Ollama evaluation (experimental / opt-in)

Orchestrator can use the explicitly selected Ollama local worker without replacing any production Codex, Claude or OpenCode worker. The adapter uses OpenCode as the tool-capable agent, Ollama as the inference runtime, and the existing Git worktree, verification and evidence pipeline.

Support state: mock-based unit tests committed; real Windows + Ollama + OpenCode end-to-end validation remains necessary. Do not claim this works on SeaCommons production yet.

## Windows setup

Use a regular, non-Administrator PowerShell session. Install Python 3.11+, Git, Ollama, Node.js and OpenCode from their official sources.

~~~powershell
git clone https://github.com/suezcanal-xyz/orchestrator.git
cd orchestrator
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"
python -m pytest -q
npm install -g opencode-ai
ollama pull qwen3:4b
ollama list
orchestrator doctor
Invoke-RestMethod http://127.0.0.1:11434/api/tags
~~~

The exact Ollama model name must appear in the local model list. Override the default name if needed:

~~~powershell
$env:ORCHESTRATOR_OLLAMA_MODEL = "qwen3:4b"
~~~

Create a **disposable** demonstration Git repository under C:\lab\demo with a Python bug, regression test and explicit verification command in docs/PLAN.md.

Read-only reconciliation (does change the demo plan/task store, but does not edit source):

~~~powershell
orchestrator ingest C:\lab\demo "Inspect the arithmetic bug and propose a regression-tested fix" --worker ollama-local
~~~

Allow edits only for an isolated demo, not for a production clone:

~~~powershell
$env:ORCHESTRATOR_OLLAMA_ALLOW_EDIT = "1"
orchestrator run C:\lab\demo --worker ollama-local --prompt "Fix the arithmetic bug and add a regression test" --max-debug-attempts 1
~~~

**Important:** the public CLI --worker flag only overrides implementation. Debug/review may use existing cloud policies. Do not claim local-only execution on a managed project unless all three stages are configured to ollama-local; see private-layer lab projects.

## What the worker enforces and what it does not

- Uses provider allowlist with only Ollama, its OpenAI-compatible endpoint pinned to 127.0.0.1:11434/v1, and refuses model names containing cloud or provider prefixes.
- Fails closed if the selected model is not installed or Ollama is unreachable.
- Uses OpenCode inline configuration and denies tool-based shell, web and external-directory operations. Read-only mode denies edit; editing requires ORCHESTRATOR_OLLAMA_ALLOW_EDIT=1.
- Orchestrator runs the declared verification commands outside the model process.
- Nothing in the worker provides OS-level sandboxing. Pre-existing OpenCode plugins, external MCP config, inherited credentials and network connectivity remain possible exfiltration vectors. A disconnected VM or outbound firewall is required to independently certify a local-only/offline run.
- Ollama/OpenCode currently recommends at least a 64K context for agentic work. This is a significant resource requirement on a CPU-only i7-8650U, even with 32 GB RAM. Starting a model does not prove agentic coding performance. Benchmark small tasks first.
- Do not run Orchestrator with Administrator rights. Do not grant local agents access to live SeaCommons datasets, API keys, SSH credentials, databases or production infrastructure.

## Gradual Suez and SeaCommons rollout

1. Clone the core and private repo alongside a disposable demo repo on the Windows workstation.
2. Record Ollama version, model digest, OpenCode version, CPU/RAM and the exact prompt.
3. Start with read-only local coding evaluation; record full failures, wall-clock time, memory consumption and deterministic verification evidence.
4. Only then allow edit on the demo and run reproducible tests.
5. For Suez and SeaCommons, use isolated nonproduction clones without secrets, and the seacommons-lab / suez-lab private profiles. The lab-specific policy must keep implement/debug/review local, irrespective of the production plan's project name.
6. Use offline copies of small tasks from the project, not the live services. Human-review all changes and never auto-merge or deploy.
7. When comparing cloud vs local, record whether each run made external requests. Do not silently fail over to a cloud model.

The adapter is intended to make experiments *measurable*, not to assert that a small CPU-run local model can replace production-grade agents.

Official integration: https://docs.ollama.com/integrations/opencode
OpenCode docs: https://opencode.ai/docs/providers/
