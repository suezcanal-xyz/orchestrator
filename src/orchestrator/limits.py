"""Recognise a subscription session / usage-limit hit in agent CLI output.

A long run on a Codex or Claude plan can exhaust a rolling usage window
mid-flight. That is not a bug in the code being worked on and not a task
that "failed" -- the run should stop cleanly, say why and (when the CLI
told us) until when, and be resumable, rather than raise a generic error
or spin the debug loop against a wall.

This module is just the detector. `engine.run` acts on it; `docs/
SESSION-LIMITS.md` is the fuller design.
"""

from __future__ import annotations

import re

# A phrase that means "you are out of quota for now". Kept broad -- the
# exact wording from each CLI changes, and a false positive only pauses a
# run that a re-run resumes.
_LIMIT_PHRASE = re.compile(
    r"(?:hit|reached|exceeded)\s+your\s+(?:session|usage|weekly|daily)\s+limit"
    r"|(?:session|usage|weekly|daily)\s+limit\s+(?:reached|exceeded)"
    r"|usage\s+limit\s+reached"
    r"|\bquota\s+exceeded\b"
    r"|\btoo\s+many\s+requests\b"
    r"|\brate[_\s-]?limit(?:ed)?\b"
    r"|\b429\b",
    re.IGNORECASE,
)

# The reset time, if the message carried one. Tried in order.
_RESET_HINTS = [
    re.compile(r"reset[s]?\s+(?:at\s+|after\s+)?([0-9][^.\n,;]*)", re.IGNORECASE),
    re.compile(r"(?:retry[-\s]after|retry\s+after)[:\s]+([^\s.,;]+)", re.IGNORECASE),
    re.compile(r"\bin\s+(\d+\s*(?:seconds?|minutes?|hours?|s|m|h))\b", re.IGNORECASE),
    re.compile(r"reset[s]?\s+(?:at\s+|after\s+)?([A-Za-z][^.\n,;]*)", re.IGNORECASE),
]


def session_limit_hint(*texts: str | None) -> str | None:
    """If any text looks like a session/usage-limit message, return a short
    reset hint ("2:40pm", "60s", "after midnight") -- or the sentinel
    ``"unknown"`` when the message matched but carried no reset time.
    Returns ``None`` when nothing matched.
    """
    for text in texts:
        if not text or not _LIMIT_PHRASE.search(text):
            continue
        for pat in _RESET_HINTS:
            m = pat.search(text)
            if m:
                return m.group(1).strip(" .\t)")
        return "unknown"
    return None
