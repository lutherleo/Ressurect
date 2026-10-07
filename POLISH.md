# Polish pass rules (manual, in Claude Code)

This is the **only** place wording changes. The pipeline stops at `selected.json`;
you then optionally produce `polished.json`, and `resume check` guards it.

## How to run it

1. Copy `applications/<slug>/selected.json` to `applications/<slug>/polished.json`.
2. Edit **only** the `text` field of bullets, to mirror the job description's
   terminology and phrasing.
3. Run `resume check <slug>`. Fix every ERROR. Review every WARN.
4. `resume render <slug>` will use `polished.json` only if the check has no errors;
   otherwise it falls back to `selected.json`.

## Rules (what `check` enforces)

- **Do not** add, remove, or reorder any item or bullet. Every `id` stays, in order.
- **Do not** change anything outside bullet `text`: not `profile`, `skills`,
  `education`, `certifications`, and not an item's non-bullet fields (`org`, `role`,
  dates, `tech`, `link`, …).
- **Do not** add, change, or drop any number or metric. "480ms", "12k", "3.8/4.0"
  must survive verbatim.
- **Do not** introduce technologies, tools, titles, or responsibilities that are
  not already somewhere in `corpus.json`. A capitalized / all-caps / skills-vocab
  term that does not occur in the corpus is flagged as a possible invented claim.

## Rule of thumb

Rephrase; never embellish. If the job description says "gRPC" and your corpus only
has "REST", you may not write "gRPC". Only the candidate editing `corpus.json`
adds new facts.
