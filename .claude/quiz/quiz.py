#!/usr/bin/env python3
"""Pop-quiz for Claude Code — same-terminal, two-hook design.

The quiz lives entirely in your one terminal via two cooperating hooks:

* STOP mode (default): the `Stop` hook fires when Claude finishes a reply. It
  reads the last assistant message, asks the Claude API for one multiple-choice
  question, saves the question + correct answer to pending_quiz.json, prints the
  question to the user (stderr + exit 1 → Claude Code shows stderr to the user),
  and exits.

* ANSWER mode (--answer): the `UserPromptSubmit` hook fires on your next message.
  If a quiz is pending and the message is a/b/c, it grades it, records the result
  in quiz_score.json, prints the verdict, and BLOCKS the message (exit 2) so your
  answer is not sent to Claude as a chat turn. Any other message abandons the
  pending quiz and passes through normally.

Why two hooks instead of an inline prompt: Claude Code is a full-screen TUI that
owns the terminal in raw mode — a hook can't read your keystrokes directly, so
"your answer" is delivered as your next prompt and intercepted here.

Standard library only.
"""

import json
import os
import random
import re
import sys
import time
import urllib.request
import urllib.error
from datetime import datetime, timezone

# --- config ----------------------------------------------------------------
HERE = os.path.dirname(os.path.abspath(__file__))
SCORE_FILE = os.path.join(HERE, "quiz_score.json")
PENDING_FILE = os.path.join(HERE, "pending_quiz.json")
ENV_FILE = os.path.join(HERE, ".env")             # KEY=VALUE lines
DEBUG_LOG = os.path.join(HERE, "debug.log")
DIFFICULTY_FILE = os.path.join(HERE, "difficulty.txt")
MODEL = "claude-haiku-4-5-20251001"               # small/fast/cheap
API_URL = "https://api.anthropic.com/v1/messages"

# --- difficulty levels -----------------------------------------------------
DEFAULT_LEVEL = "medium"
LEVEL_ORDER = ["easy", "medium", "hard", "expert"]
LEVELS = {
    "easy": {
        "label": "EASY", "stars": "★☆☆☆",
        "instruction": (
            "DIFFICULTY: EASY. Ask about a single fact stated explicitly and "
            "prominently in the message. Keep it short; make the two wrong "
            "options obviously different from the correct one."
        ),
    },
    "medium": {
        "label": "MEDIUM", "stars": "★★☆☆",
        "instruction": (
            "DIFFICULTY: MEDIUM. Test whether the reader understood the main "
            "point or how something works. Wrong options should be plausible "
            "but clearly incorrect to someone who read carefully."
        ),
    },
    "hard": {
        "label": "HARD", "stars": "★★★☆",
        "instruction": (
            "DIFFICULTY: HARD. Require inference, application, or connecting two "
            "ideas rather than recalling a stated fact. Make all three options "
            "plausible; the wrong ones should reflect realistic misunderstandings "
            "so only a reader who truly understood picks the right one."
        ),
    },
    "expert": {
        "label": "EXPERT", "stars": "★★★★",
        "instruction": (
            "DIFFICULTY: EXPERT. Probe a subtle edge case, trade-off, limitation, "
            "or nuance. Distractors must be very plausible — common misconceptions "
            "or near-correct statements with a single critical flaw. Avoid anything "
            "answerable by skimming."
        ),
    },
}


def get_difficulty():
    """Configured level: env var QUIZ_LEVEL > difficulty.txt > default."""
    lvl = os.environ.get("QUIZ_LEVEL", "").strip().lower()
    if not lvl and os.path.exists(DIFFICULTY_FILE):
        try:
            with open(DIFFICULTY_FILE) as f:
                lvl = f.read().strip().lower()
        except OSError:
            lvl = ""
    if lvl in LEVELS or lvl == "adaptive":
        return lvl
    return DEFAULT_LEVEL


def set_difficulty(level):
    level = level.strip().lower()
    if level not in LEVELS and level != "adaptive":
        return False
    with open(DIFFICULTY_FILE, "w") as f:
        f.write(level + "\n")
    return True


def resolve_level(configured, score):
    """Turn 'adaptive' into a concrete level based on recent accuracy."""
    if configured != "adaptive":
        return configured
    recents = [h["answered_correct"] for h in score.get("history", [])
               if "answered_correct" in h][-5:]
    if not recents:
        return "medium"
    acc = sum(recents) / len(recents)
    if acc >= 0.8:
        return "expert" if len(recents) >= 3 else "hard"
    if acc >= 0.6:
        return "hard"
    if acc >= 0.4:
        return "medium"
    return "easy"


def log(msg):
    line = f"[quiz] {msg}"
    try:
        with open(DEBUG_LOG, "a") as f:
            f.write(f"{datetime.now(timezone.utc).isoformat()} {line}\n")
    except OSError:
        pass


# --- shared helpers --------------------------------------------------------
def get_api_key():
    key = os.environ.get("ANTHROPIC_API_KEY")
    if key:
        return key.strip()
    if os.path.exists(ENV_FILE):
        with open(ENV_FILE) as f:
            for line in f:
                line = line.strip()
                if line.startswith("ANTHROPIC_API_KEY="):
                    return line.split("=", 1)[1].strip().strip('"').strip("'")
    return None


def load_score():
    if os.path.exists(SCORE_FILE):
        try:
            with open(SCORE_FILE) as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            pass
    return {"total": 0, "correct": 0, "history": []}


def save_score(score):
    with open(SCORE_FILE, "w") as f:
        json.dump(score, f, indent=2)


def read_payload():
    raw = sys.stdin.read()
    try:
        return json.loads(raw) if raw.strip() else {}
    except json.JSONDecodeError:
        return {}


# --- STOP mode: generate + show question -----------------------------------
def last_assistant_text(transcript_path):
    if not transcript_path or not os.path.exists(transcript_path):
        return ""
    last = ""
    with open(transcript_path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue
            msg = obj.get("message", obj)
            if msg.get("role") != "assistant":
                continue
            content = msg.get("content", "")
            if isinstance(content, str):
                text = content
            else:
                text = "".join(
                    b.get("text", "")
                    for b in content
                    if isinstance(b, dict) and b.get("type") == "text"
                )
            if text.strip():
                last = text
    return last


LANG_BY_EXT = {
    ".py": "python", ".js": "javascript", ".jsx": "javascript",
    ".ts": "typescript", ".tsx": "typescript", ".java": "java", ".c": "c",
    ".h": "c", ".cpp": "cpp", ".cc": "cpp", ".go": "go", ".rs": "rust",
    ".rb": "ruby", ".php": "php", ".sh": "bash", ".bash": "bash",
    ".json": "json", ".html": "html", ".css": "css", ".sql": "sql",
    ".yaml": "yaml", ".yml": "yaml", ".md": "markdown", ".tf": "hcl",
}
FENCE_RE = re.compile(r"```(\w+)?\n(.*?)```", re.DOTALL)
# substrings that mark a fenced block as our own quiz output, not real code
QUIZ_MARKERS = ("POP QUIZ", "Reply with", "<!--CODE_QUIZ-->", "╔", "🧠",
                "Difficulty:", "Score:")


def _lang_from_path(path):
    return LANG_BY_EXT.get(os.path.splitext(path or "")[1].lower(), "")


def _looks_like_quiz(code):
    return any(m in code for m in QUIZ_MARKERS)


def _codes_in_message(msg):
    """(kind, code, language) triples in one assistant message.

    kind is "tool" for Write/Edit/MultiEdit/NotebookEdit contents (definitely
    real code) or "fence" for ```fenced``` blocks in text (filtered to drop our
    own quiz output)."""
    out = []
    content = msg.get("content", "")
    if isinstance(content, str):
        blocks = [{"type": "text", "text": content}]
    else:
        blocks = content if isinstance(content, list) else []
    for b in blocks:
        if not isinstance(b, dict):
            continue
        btype = b.get("type")
        if btype == "text":
            for lang, code in FENCE_RE.findall(b.get("text", "")):
                code = code.rstrip("\n")
                if code.strip() and not _looks_like_quiz(code):
                    out.append(("fence", code, lang or ""))
        elif btype == "tool_use":
            name = b.get("name", "")
            inp = b.get("input", {}) or {}
            path = inp.get("file_path") or inp.get("notebook_path") or ""
            lang = _lang_from_path(path)
            if name == "Write" and inp.get("content"):
                out.append(("tool", inp["content"].rstrip("\n"), lang))
            elif name == "Edit" and inp.get("new_string"):
                out.append(("tool", inp["new_string"].rstrip("\n"), lang))
            elif name == "MultiEdit" and inp.get("edits"):
                joined = "\n".join(e.get("new_string", "")
                                   for e in inp["edits"] if e.get("new_string"))
                if joined.strip():
                    out.append(("tool", joined, lang))
            elif name == "NotebookEdit" and inp.get("new_source"):
                out.append(("tool", inp["new_source"].rstrip("\n"),
                            lang or "python"))
    return out


def extract_last_code(transcript_path):
    """Return (code, language) of the most recent code block in the transcript,
    or None.

    Scans every assistant message and keeps the last code found. The /quiz turn
    that invokes this only contains a tool call (no code), so "most recent code"
    is the code from the last reply that actually produced any — without relying
    on fragile turn-boundary detection (a slash command logs two consecutive
    user messages, which broke a between-the-user-prompts approach).
    """
    if not transcript_path or not os.path.exists(transcript_path):
        return None
    last_tool = None   # Write/Edit code — preferred
    last_fence = None  # ```fenced``` code — fallback
    with open(transcript_path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue
            msg = obj.get("message", obj)
            if msg.get("role") != "assistant":
                continue
            for kind, code, lang in _codes_in_message(msg):
                if kind == "tool":
                    last_tool = (code, lang)
                else:
                    last_fence = (code, lang)
    return last_tool or last_fence


def generate_question(api_key, source_text, level="medium"):
    source_text = source_text[:6000]
    instruction = LEVELS.get(level, LEVELS[DEFAULT_LEVEL])["instruction"]
    prompt = (
        "Write ONE multiple-choice question based ONLY on the assistant message "
        "below, with options a, b, c and exactly one correct answer.\n"
        + instruction + "\n"
        "CORRECTNESS RULES (critical — these matter most):\n"
        "- Exactly ONE option is correct. The other two must be UNAMBIGUOUSLY "
        "FALSE: a knowledgeable reader must not be able to argue either is also "
        "correct.\n"
        "- Each wrong option must contain a definite factual error vs. the "
        "message. Never use statements that are also true, merely incomplete, or "
        "true-but-off-topic.\n"
        "- The correct option must be the single, complete, best answer.\n"
        "- Ask a precise question with only one defensible answer. Avoid open "
        "'why' questions that have several valid explanations.\n"
        "STYLE RULES (strict):\n"
        "- Question: 20 words or fewer.\n"
        "- Each option: 8 words or fewer; shorter is better.\n"
        "- Options are bare answers only — no explanations, no 'because'.\n"
        "- All three options similar in length so length doesn't hint the answer.\n"
        "Before responding, silently check that BOTH wrong options are clearly "
        "false; if either could be argued correct, replace it.\n"
        "Respond with ONLY a JSON object, no prose, in this exact shape:\n"
        '{"question": "...", "options": {"a": "...", "b": "...", "c": "..."}, '
        '"correct": "a"}\n\n'
        "=== ASSISTANT MESSAGE ===\n" + source_text
    )
    q = _call_model_json(api_key, prompt)
    if not (q.get("question") and q.get("options") and q.get("correct")):
        raise ValueError(f"malformed question: {q}")
    shuffle_options(q)  # counter the model's bias toward answer "a"
    q["level"] = level
    return q


def _call_model_json(api_key, prompt, max_tokens=600):
    """POST a prompt to the API and return the JSON object in the reply."""
    body = json.dumps({
        "model": MODEL,
        "max_tokens": max_tokens,
        "messages": [{"role": "user", "content": prompt}],
    }).encode()
    req = urllib.request.Request(
        API_URL, data=body,
        headers={
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        data = json.loads(resp.read())
    text = "".join(b.get("text", "") for b in data.get("content", []))
    start = text.find("{")
    if start == -1:
        raise ValueError(f"no JSON in model reply: {text[:200]}")
    # raw_decode parses the first complete object and ignores any trailing text
    # (markdown fences, prose) — robust when a 'code' field contains braces.
    obj, _ = json.JSONDecoder().raw_decode(text[start:])
    return obj


def generate_code_question(api_key, code, language, level="medium"):
    """Build a question ABOUT a code snippet (returns extra code/language)."""
    code = code[:4000]
    instruction = LEVELS.get(level, LEVELS[DEFAULT_LEVEL])["instruction"]
    prompt = (
        "You are given CODE the assistant just produced. Write ONE multiple-choice "
        "question that tests understanding of THIS code by READING it: its purpose, "
        "default behaviour, what a parameter or branch does, a bug or edge case, or "
        "the effect of changing a line.\n"
        + instruction + "\n"
        "Include a 'code' field: the minimal relevant snippet to show the reader "
        "(15 lines max; the whole thing if short). Keep it faithful to the code.\n"
        "CORRECTNESS RULES (critical):\n"
        "- Do NOT ask anything that requires mentally executing the code, counting "
        "characters, or computing an exact numeric/string result — those answers "
        "are error-prone. Ask only what can be determined by reading the code.\n"
        "- The correct option must be verifiably true from the code as written.\n"
        "- Exactly ONE option is correct; the other two UNAMBIGUOUSLY FALSE.\n"
        "- Each wrong option has a definite error; none can be argued correct.\n"
        "GOOD styles (use one): 'What is the default behaviour?', 'Which branch "
        "runs when <flag> is true?', 'What is the purpose of <line>?', 'What does "
        "the function count/do?', 'What would change if <line> were removed?'.\n"
        "FORBIDDEN: 'What does f(<literal>) return/print?' or any question whose "
        "answer is a specific number/string you'd get by running the code.\n"
        "STYLE RULES (strict):\n"
        "- Question: 20 words or fewer.\n"
        "- Each option: 8 words or fewer; shorter is better.\n"
        "- Options are bare answers only; all three similar in length.\n"
        "Respond with ONLY this JSON, no prose:\n"
        '{"question": "...", "code": "...", "language": "' + (language or "") + '", '
        '"options": {"a": "...", "b": "...", "c": "..."}, "correct": "a"}\n\n'
        "=== LANGUAGE: " + (language or "unknown") + " ===\n"
        "=== CODE ===\n" + code
    )
    q = None
    for _ in range(3):  # regenerate if the model slips into an execution question
        cand = _call_model_json(api_key, prompt)
        if not (cand.get("question") and cand.get("code")
                and cand.get("options") and cand.get("correct")):
            continue
        q = cand
        if not _is_execution_like(cand):
            break
    if not (q and q.get("question") and q.get("options") and q.get("correct")):
        raise ValueError(f"malformed code question: {q}")
    shuffle_options(q)
    q["level"] = level
    if not q.get("language"):
        q["language"] = language or ""
    return q


_EXEC_Q_RE = re.compile(
    r"what (does|will).*(return|print|output|evaluate)"
    r"|return[s]?\b.*\b(on|for|when called|with input|with the)"
    r"|\bcalled (with|on)\b",
    re.IGNORECASE,
)


def _is_execution_like(q):
    """True if the question needs running the code (numeric/string result)."""
    opts = [str(o) for o in q.get("options", {}).values()]
    numeric = sum(bool(re.fullmatch(r"\s*(returns?\s*)?[-+]?\d+\s*", o, re.I))
                  for o in opts)
    if numeric >= 2:
        return True
    return bool(_EXEC_Q_RE.search(q.get("question", "")))


def shuffle_options(q):
    """Randomly re-assign option texts to a/b/c so the correct slot is uniform.

    Tracks by original index (not text) so duplicate option strings can't break
    the correct-answer mapping.
    """
    letters = ["a", "b", "c"]
    texts = [q["options"].get(l, "") for l in letters]
    correct_idx = letters.index(str(q["correct"]).strip().lower())
    order = list(range(3))
    random.shuffle(order)
    q["options"] = {letters[j]: texts[order[j]] for j in range(3)}
    q["correct"] = letters[order.index(correct_idx)]
    return q


def format_question(q):
    lvl = LEVELS.get(q.get("level", DEFAULT_LEVEL), LEVELS[DEFAULT_LEVEL])
    badge = f"{lvl['stars']}  {lvl['label']}"
    lines = [
        "",
        "╔══════════════════════════════════════════════════════╗",
        "║   🧠  P O P   Q U I Z                                 ║",
        "╚══════════════════════════════════════════════════════╝",
        f"   🎚️  Difficulty: {badge}",
        "",
        f"❓ {q['question']}",
        "",
    ]
    for opt in ("a", "b", "c"):
        lines.append(f"     【 {opt.upper()} 】 {q['options'].get(opt, '')}")
    lines.append("")
    lines.append("──────────────────────────────────────────────────────")
    lines.append("⌨️  Reply with  a , b , or c   ·   anything else skips")
    return "\n".join(lines)


def format_code_question(q):
    """Markdown layout for a code question — renders with real syntax
    highlighting when Claude displays it as a message (not inside an outer
    fence). The first line marks it so the /quiz handler renders it directly."""
    lvl = LEVELS.get(q.get("level", DEFAULT_LEVEL), LEVELS[DEFAULT_LEVEL])
    badge = f"{lvl['stars']} {lvl['label']}"
    lang = q.get("language", "")
    lines = [
        "<!--CODE_QUIZ-->",
        f"### 🧠 POP QUIZ · 💻 Code · {badge}",
        "",
        f"**{q['question']}**",
        "",
        f"```{lang}",
        _number_lines(q["code"]),
        "```",
        "",
    ]
    for opt in ("a", "b", "c"):
        lines.append(f"- **{opt})** {q['options'].get(opt, '')}")
    lines.append("")
    lines.append("_Reply with **a**, **b**, or **c** — anything else skips._")
    return "\n".join(lines)


def _number_lines(code):
    """Prefix each line with a right-aligned line number gutter (no separator,
    so syntax highlighting of the code stays intact)."""
    rows = code.splitlines() or [""]
    width = max(2, len(str(len(rows))))
    return "\n".join(f"{str(i).rjust(width)}  {row}"
                     for i, row in enumerate(rows, 1))


def stop_mode():
    log("=== stop hook fired ===")
    payload = read_payload()
    if payload.get("stop_hook_active"):
        return 0

    api_key = get_api_key()
    if not api_key:
        log("no API key in env or .env; skipping")
        return 0

    # The Stop hook can fire before Claude Code has flushed the final assistant
    # message to the transcript, so a single read may see 0 chars. Poll briefly.
    transcript_path = payload.get("transcript_path")
    text = ""
    for _ in range(8):  # up to ~2s
        text = last_assistant_text(transcript_path)
        if len(text.strip()) >= 40:
            break
        time.sleep(0.25)
    log(f"assistant text length: {len(text.strip())}")
    if len(text.strip()) < 40:
        log("assistant message too short; skipping")
        return 0

    level = resolve_level(get_difficulty(), load_score())
    log(f"difficulty: {level}")
    try:
        q = generate_question(api_key, text, level)
    except (urllib.error.URLError, urllib.error.HTTPError) as e:
        log(f"API call failed: {e}")
        return 0
    except (ValueError, json.JSONDecodeError) as e:
        log(f"could not parse question: {e}")
        return 0

    with open(PENDING_FILE, "w") as f:
        json.dump(q, f)
    log("question saved; showing to user")
    # JSON output with systemMessage => clean notice to the user (no error framing)
    print(json.dumps({
        "systemMessage": format_question(q),
        "suppressOutput": True,
    }))
    return 0


# --- ONDEMAND mode: /quiz slash command ------------------------------------
def _project_transcript_dir():
    return os.path.join(os.path.expanduser("~"), ".claude", "projects",
                        os.getcwd().replace("/", "-"))


def find_latest_transcript():
    """Newest .jsonl transcript for the current project, or None."""
    base = _project_transcript_dir()
    if not os.path.isdir(base):
        return None
    files = [os.path.join(base, f) for f in os.listdir(base)
             if f.endswith(".jsonl")]
    return max(files, key=os.path.getmtime) if files else None


def session_transcript():
    """The transcript of THIS session (via CLAUDE_CODE_SESSION_ID), so /quiz
    targets the invoking session even when several run in the same project.
    Falls back to the newest transcript if the env var is unavailable."""
    sid = os.environ.get("CLAUDE_CODE_SESSION_ID", "").strip()
    if sid:
        p = os.path.join(_project_transcript_dir(), sid + ".jsonl")
        if os.path.exists(p):
            return p
    return find_latest_transcript()


def ondemand_mode(args):
    """Generate a quiz on demand (for the /quiz slash command)."""
    log("=== ondemand (/quiz) invoked ===")
    api_key = get_api_key()
    if not api_key:
        print("⚠️  Quiz unavailable: no ANTHROPIC_API_KEY set.")
        return 0

    extras = [a for a in args if not a.startswith("--")]
    code_mode = "code" in (e.lower() for e in extras) or "--code" in args
    paths = [e for e in extras if e.lower() != "code"]
    path = paths[0] if paths else session_transcript()
    log(f"transcript: {path}")
    level = resolve_level(get_difficulty(), load_score())

    if code_mode:
        found = extract_last_code(path)
        if not found:
            print("⚠️  No code found in the last response — nothing to quiz on.")
            return 0
        code, language = found
        try:
            q = generate_code_question(api_key, code, language, level)
        except (urllib.error.URLError, urllib.error.HTTPError) as e:
            print(f"⚠️  Quiz generation failed (network): {e}")
            return 0
        except (ValueError, json.JSONDecodeError) as e:
            print(f"⚠️  Quiz generation failed (parse): {e}")
            return 0
        with open(PENDING_FILE, "w") as f:
            json.dump(q, f)
        log("ondemand code question saved; printing")
        print(format_code_question(q))
        return 0

    text = last_assistant_text(path)
    if len(text.strip()) < 40:
        print("⚠️  Nothing substantial in the last reply to quiz on yet.")
        return 0
    try:
        q = generate_question(api_key, text, level)
    except (urllib.error.URLError, urllib.error.HTTPError) as e:
        print(f"⚠️  Quiz generation failed (network): {e}")
        return 0
    except (ValueError, json.JSONDecodeError) as e:
        print(f"⚠️  Quiz generation failed (parse): {e}")
        return 0

    with open(PENDING_FILE, "w") as f:
        json.dump(q, f)
    log("ondemand question saved; printing")
    print(format_question(q))
    return 0


# --- ANSWER mode: grade the next prompt ------------------------------------
ANSWER_RE = re.compile(r"^\s*([abc])\s*[\).:,-]?\s*$", re.IGNORECASE)


def answer_mode():
    log("=== answer hook fired ===")
    if not os.path.exists(PENDING_FILE):
        return 0  # no quiz pending → let the prompt through

    payload = read_payload()
    prompt = payload.get("prompt", "")
    m = ANSWER_RE.match(prompt)

    # consume the pending quiz either way (answered or abandoned)
    try:
        with open(PENDING_FILE) as f:
            q = json.load(f)
    except (OSError, json.JSONDecodeError):
        q = None
    try:
        os.remove(PENDING_FILE)
    except OSError:
        pass

    if not m or q is None:
        log("prompt is not an a/b/c answer; passing through")
        return 0  # not an answer → send the message to Claude normally

    answer = m.group(1).lower()
    correct = str(q["correct"]).strip().lower()
    is_correct = answer == correct

    score = load_score()
    score["total"] += 1
    if is_correct:
        score["correct"] += 1
    score["history"].append({
        "ts": datetime.now(timezone.utc).isoformat(),
        "question": q["question"],
        "level": q.get("level", DEFAULT_LEVEL),
        "answered_correct": is_correct,
    })
    save_score(score)
    pct = 100 * score["correct"] // score["total"]

    if is_correct:
        banner = "✅✅✅  C O R R E C T !  ✅✅✅"
    else:
        banner = (f"❌  Not quite — the answer was  【 {correct.upper()} 】 "
                  f"{q['options'].get(correct, '')}")
    bar = "═" * 54
    # Claude Code displays the `reason` of a blocked prompt to the user, so the
    # verdict goes here (systemMessage is NOT shown for a blocked UserPromptSubmit).
    message = (
        f"\n{bar}\n"
        f"   {banner}\n"
        f"   🏆 Score: {score['correct']}/{score['total']}  ({pct}%)\n"
        f"{bar}"
    )
    print(json.dumps({
        "decision": "block",
        "reason": message,
        "suppressOutput": True,
    }))
    return 0


def print_status():
    configured = get_difficulty()
    score = load_score()
    effective = resolve_level(configured, score)
    print(f"Difficulty: {configured}"
          + (f"  (currently → {effective})" if configured == "adaptive" else ""))
    if score["total"]:
        pct = 100 * score["correct"] // score["total"]
        print(f"Score: {score['correct']}/{score['total']} ({pct}%)")
    print(f"Levels: {', '.join(LEVEL_ORDER)}, adaptive")


def main():
    args = sys.argv[1:]
    if "--answer" in args:
        return answer_mode()
    if "--ondemand" in args:
        return ondemand_mode(args)
    if "--status" in args:
        print_status()
        return 0
    if "--level" in args:
        i = args.index("--level")
        val = args[i + 1] if i + 1 < len(args) else ""
        if set_difficulty(val):
            print(f"✅ Difficulty set to: {val.lower()}")
            return 0
        print(f"❌ Unknown level: {val!r}. "
              f"Choose: {', '.join(LEVEL_ORDER)}, adaptive")
        return 1
    return stop_mode()


if __name__ == "__main__":
    sys.exit(main())
