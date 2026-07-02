#!/usr/bin/env python3
"""Peer-programming mode for Claude Code.

When ON, a `UserPromptSubmit` hook (--inject) silently adds a directive to
Claude's context telling it to write code with a few `complete here (N)` blanks
instead of the finished solution — and to do so WITHOUT any "exercise" narration.
Because Claude writes the blanks directly, what the transcript shows is exactly
what lands in the file, and the full solution is never revealed.

The /peer-check slash command grades what the user filled in by reasoning about
the surrounding code (there is no stored solution).

State is one tiny file next to this script:
  enabled.txt -> "on" / "off"   (default: on)

Standard library only.
"""

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ENABLED_FILE = os.path.join(HERE, "enabled.txt")

DIRECTIVE = """\
<peer-mode>
Peer-programming mode is ON. If this turn writes or edits code, hand the user
code with a few blanks to fill in — NOT the finished solution.

HOW TO MAKE A BLANK: DELETE the real code of the chosen line and leave ONLY the
placeholder comment in its place. The correct code must NOT remain on that line
or anywhere else in the file. Appending a comment to working code is WRONG.

WRONG (the answer is still there — never do this):
        count = count + 1        # complete here (1)
        return count             # complete here (2)

RIGHT (real code deleted, placeholder only):
        # complete here (1)
        pass
    # complete here (2)

Rules:
- Blank 2-4 KEY leaf statements (the core computation, a return value, an
  assignment). Keep imports, signatures, headers, boilerplate and tests intact.
- Never blank a structural/header line (if/for/def/class/…).
- If deleting a statement leaves a block empty, add a bare `pass` on its own
  line so the file still parses (see RIGHT). `pass` is the ONLY code you may add;
  never leave the real statement behind.
- Placeholders are bare and numbered: `# complete here (1)` — no hint, no
  description of what belongs there.
- Reply completely NORMALLY and briefly. Do NOT mention "peer mode", "exercise",
  "blanks", or that anything is missing. Never reveal the solution.

The user fills in the blanks and runs /peer-check to be graded.
</peer-mode>"""


def read_enabled():
    if not os.path.exists(ENABLED_FILE):
        return True  # default ON once installed
    try:
        with open(ENABLED_FILE) as f:
            return f.read().strip().lower() != "off"
    except OSError:
        return True


def set_enabled(on):
    with open(ENABLED_FILE, "w") as f:
        f.write("on\n" if on else "off\n")


def inject_mode():
    # Drain stdin (Claude Code pipes a JSON payload we don't need), then add the
    # directive to context only when enabled. UserPromptSubmit stdout on exit 0
    # is appended to the model's context.
    try:
        sys.stdin.read()
    except OSError:
        pass
    if read_enabled():
        print(DIRECTIVE)
    return 0


def main():
    args = sys.argv[1:]
    if "--inject" in args:
        return inject_mode()
    if "--on" in args:
        set_enabled(True)
        print("✅ Peer mode is ON — new code will come with `complete here` blanks.")
        return 0
    if "--off" in args:
        set_enabled(False)
        print("⏹️  Peer mode is OFF — code will be written complete.")
        return 0
    if "--status" in args:
        print("Peer mode: " + ("ON" if read_enabled() else "OFF"))
        return 0
    print("usage: peer.py [--inject|--on|--off|--status]")
    return 1


if __name__ == "__main__":
    sys.exit(main())
