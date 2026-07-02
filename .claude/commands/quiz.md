---
description: Pop quiz from Claude's last response (add "code" to quiz the code)
argument-hint: [code]
allowed-tools: Bash(python3 /home/radu/projects/easy-peasy/.claude/quiz/quiz.py --ondemand:*)
---

The user wants a pop quiz on your **previous** response.

As your very first action and with NO text before it, run:

`python3 /home/radu/projects/easy-peasy/.claude/quiz/quiz.py --ondemand $ARGUMENTS`

(`$ARGUMENTS` may be empty for a general quiz, or `code` to quiz specifically on
code from your last response.)

The script generates one multiple-choice question at the configured difficulty,
saves it as the pending quiz, and prints it. Then display its output to the user
and add nothing else (no commentary, no answer) — they reply a/b/c and the hook
grades it. Render the output based on its first line:

- If it starts with `<!--CODE_QUIZ-->`: drop that marker line and show the rest
  **as markdown** (do NOT wrap it in a code fence) so the code block is
  syntax-highlighted like normal code output.
- Otherwise: show it inside a plain ``` code fence exactly as printed, to
  preserve the box layout.
