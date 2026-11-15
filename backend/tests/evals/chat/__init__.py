"""Spec C — chat-advisor quality eval harness.

Aligns with Spec A's u-eval-a convention so per-suite fixture data is
isolated. Spec C uses u-eval-c.
"""

EVAL_USER_ID = "u-eval-c"
EVAL_HEADERS = {"X-Eval-User-Id": EVAL_USER_ID}
