# calc-demo

A deliberately tiny project used as the orchestrator's example repository
(spec section 24) and as the fixture for the v0.1.0 closed-development-loop
acceptance test (spec section 22).

`src/calc/__init__.py` implements `add()` correctly. `subtract()` and
`multiply()` are intentionally missing / wrong, so that pointing
`orchestrator run` at this repository has real, verifiable work to do and
at least one verification failure to debug through.

This directory ships as plain files (no embedded `.git`) inside the
`orchestrator` repository. To actually run the orchestrator against it,
copy it somewhere else first and `git init` there:

```bash
cp -r examples/demo-repo /tmp/calc-demo
cd /tmp/calc-demo
git init -b main && git add -A && git commit -m "initial"
orchestrator run . --prompt "subtract and multiply are broken, fix them"
```
