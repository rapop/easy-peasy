---
description: Grade the code the user filled into the `complete here` blanks
argument-hint: [on|off|status]
allowed-tools: Bash(python3 /home/radu/projects/easy-peasy/.claude/peer/peer.py:*), Read
---

`$ARGUMENTS` selects the mode:

- If `$ARGUMENTS` is `on`, `off`, or `status`: run
  `python3 /home/radu/projects/easy-peasy/.claude/peer/peer.py --$ARGUMENTS`,
  show its output, and stop. (This toggles whether new code comes with
  `complete here` blanks.)

- Otherwise (empty or anything else): GRADE the user's completions.

To grade:

1. Figure out which file to check: the code file from this conversation that had
   `complete here (N)` placeholders. If it's ambiguous, ask the user which file.
2. `Read` that file (its current, user-edited state).
3. There is NO stored solution — judge each blank yourself. For every
   `complete here (N)` spot, look at what the user put there and decide whether it
   is **functionally correct** given the surrounding code, the function/variable
   names, any docstring, the hint that was in the placeholder, and the task the
   user originally asked for. Accept any solution that works, not only the one you
   would have written.
4. Report per blank:
   - ✅ correct — one line confirming it.
   - ❌ incorrect — explain clearly WHY it's wrong (the bug, edge case, or
     misunderstanding), then show a suggested correct version in a fenced block.
   - ⬜ untouched — if a `complete here` placeholder is still there, say so.
   End with an overall verdict and score (e.g. 3/4 correct).

CRITICAL — do NOT edit the user's file. Only explain and suggest. After the
report, ask whether they'd like you to apply any corrections, and edit the file
ONLY if they explicitly say yes.
