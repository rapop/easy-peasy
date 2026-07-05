# easy-peasy

A learning-focused Claude Code setup with two teaching hooks and two slash
commands:

- **Half-code (peer) hook** — new code arrives with a few `complete here (N)`
  blanks for you to fill in.
- **Quiz hook** — pop quizzes about Claude's replies (or its code).
- **`/peer-check`** — grades the blanks you filled in, and toggles the peer hook.
- **`/quiz`** — asks a pop quiz on demand.

Everything lives under `.claude/` and uses only the Python standard library
(the quiz needs an Anthropic API key to generate questions).

---

## Half-code (peer) hook

When ON, a `UserPromptSubmit` hook (`.claude/peer/peer.py --inject`) silently
tells Claude to hand you code with 2–4 key lines replaced by
`# complete here (N)` placeholders instead of the finished solution. You fill in
the blanks, then run `/peer-check` to be graded.

### Enable / disable

State is one small file: `.claude/peer/enabled.txt` (`on` / `off`, default `on`).
The easiest way to flip it is through the slash command or the script directly:

```bash
# via the slash command (inside Claude Code)
/peer-check on       # turn blanks ON
/peer-check off      # turn blanks OFF — code is written complete
/peer-check status   # show current state

# or run the script directly (from the project root)
python3 .claude/peer/peer.py --on
python3 .claude/peer/peer.py --off
python3 .claude/peer/peer.py --status
```

When OFF, the hook still runs but injects nothing, so Claude writes normal,
complete code.

### Turn the hook off entirely

To stop the hook from running at all, remove its block from
`.claude/settings.json` under `hooks.UserPromptSubmit` (the entry whose command
is `... /.claude/peer/peer.py --inject`). Re-add it to switch the feature back on.

---

## Quiz hook

The quiz uses cooperating hooks in `.claude/quiz/quiz.py`:

- **Answer grading** (`--answer`, on `UserPromptSubmit`) — when a quiz is
  pending and your next message is `a`, `b`, or `c`, it grades the answer,
  updates your score, and blocks the message so it isn't sent to Claude as chat.
- **Auto pop-quiz** (`Stop` hook) — fires when Claude finishes a reply and pops
  a question about that reply. This one is **optional**: it ships as a template
  in `.claude/settings.json.backup`, not in the active `.claude/settings.json`.

There is no `enabled.txt` toggle for the quiz — you enable/disable it by editing
`.claude/settings.json`.

### Enable / disable

**Answer grading + on-demand `/quiz`** (the default): keep this entry in
`hooks.UserPromptSubmit` of `.claude/settings.json`:

```json
{
  "hooks": [
    { "type": "command",
      "command": "python3 /home/radu/projects/easy-peasy/.claude/quiz/quiz.py --answer",
      "timeout": 15 }
  ]
}
```

**Automatic pop-quiz after every reply:** add a `Stop` hook (copy it from
`.claude/settings.json.backup`):

```json
"Stop": [
  {
    "hooks": [
      { "type": "command",
        "command": "python3 /home/radu/projects/easy-peasy/.claude/quiz/quiz.py",
        "timeout": 30 }
    ]
  }
]
```

**Disable the quiz completely:** remove the quiz entries from
`.claude/settings.json` (the `--answer` `UserPromptSubmit` entry and the `Stop`
entry). `/quiz` still needs the `--answer` entry to grade your replies, so remove
that last if you want on-demand quizzes to keep working.

### API key & difficulty

The quiz calls the Anthropic API to write questions. Provide a key via the
`ANTHROPIC_API_KEY` environment variable or a `ANTHROPIC_API_KEY=...` line in
`.claude/quiz/.env`. Without a key the quiz silently does nothing.

Difficulty is `easy`, `medium`, `hard`, `expert`, or `adaptive` (default
`medium`), stored in `.claude/quiz/difficulty.txt`:

```bash
python3 .claude/quiz/quiz.py --level hard    # set difficulty
python3 .claude/quiz/quiz.py --status        # show difficulty + score
```

---

## Using `/quiz`

Ask for a pop quiz about Claude's **most recent** reply:

```
/quiz          # one multiple-choice question about the last reply
/quiz code     # quiz specifically on the code from the last reply
```

Answer by replying with just `a`, `b`, or `c`. Anything else skips the quiz and
is sent to Claude normally. Your running score is tracked in
`.claude/quiz/quiz_score.json`.

## Using `/peer-check`

After filling in the `complete here (N)` blanks Claude left in a file:

```
/peer-check           # grade what you filled in
/peer-check on        # turn the peer hook ON
/peer-check off       # turn the peer hook OFF
/peer-check status    # show whether the peer hook is on or off
```

With no argument it grades your completions: it reads the current state of the
file, judges each blank on its merits (there's no stored solution), and reports
✅ / ❌ / ⬜ per blank plus an overall score. It only explains and suggests — it
won't edit your file unless you explicitly ask it to.
