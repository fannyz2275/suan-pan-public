FINDINGS_SYSTEM_PROMPT_TEMPLATE = """You are guiding the user through a short review of \
{count} backend-detected findings. For each finding, emit ONE assistant turn containing \
a brief plain-language explanation followed by EXACTLY one tag of the form:

<finding id="{{id}}" kind="{{kind}}">{{1-2 line evidence summary}}</finding>

After emitting a tag, STOP and wait for the user's reply (they will click a button which \
posts "Confirmed: ..." or "Rejected: ..."). Only then move to the next finding.

Findings to review (in order):
{listing}

When all findings are reviewed (or the user says stop), emit a one-sentence summary \
of what was confirmed/rejected. Do NOT skip findings.
"""


def render_findings_prompt(findings) -> str:
    listing = "\n".join(f"- id={f.id} kind={f.kind} :: {f.title}" for f in findings)
    return FINDINGS_SYSTEM_PROMPT_TEMPLATE.format(count=len(findings), listing=listing)
