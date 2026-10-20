"""Export the Maravi lead sessions and every session started beneath them to Markdown."""

from __future__ import annotations

import glob
import json
import os
import re
import sys
from datetime import datetime, timedelta, timezone

HOME = os.path.expanduser("~")
META_DIR = glob.glob(f"{HOME}/Library/Application Support/Claude/claude-code-sessions/*/*/")
PROJECTS = f"{HOME}/.claude/projects"
OUT = sys.argv[1]
ROOTS = {
    "local_f904ff92-5b7b-4ad8-aeb6-ff925baf0660": "lead-backend",
    "local_88cb7aa2-7b7b-4480-ad7a-6b405bf4494e": "code-reviewer",
    "local_d8df4721-40f7-4d32-9ad6-08e0b84b0d1d": "lead-frontend",
}
KICKOFF = "414590bd"
SP = timezone(timedelta(hours=-3))

# ---------------------------------------------------------------- metadata
meta: dict[str, dict] = {}
for d in META_DIR:
    for f in glob.glob(d + "local_*.json"):
        o = json.load(open(f))
        if "/Maravi" in (o.get("cwd") or "") + (o.get("originCwd") or ""):
            meta[o["sessionId"]] = o
# Fix the Lead Frontend id by title (the literal above is only a guess at its suffix).
for sid, o in meta.items():
    if o.get("title") == "Lead Frontend":
        ROOTS = {(sid if v == "lead-frontend" else k): v for k, v in ROOTS.items()}

def parent(o: dict) -> str | None:
    sf = o.get("spawnedFrom") or {}
    return sf.get("sessionId")

children: dict[str, list[str]] = {}
for sid, o in meta.items():
    p = parent(o)
    if p:
        children.setdefault(p, []).append(sid)
for v in children.values():
    v.sort(key=lambda s: meta[s].get("createdAt", 0))

def transcript_files(o: dict) -> list[str]:
    ids = [i for i in (o.get("priorCliSessionIds") or []) + [o.get("cliSessionId")] if i]
    out = []
    for i in dict.fromkeys(ids):
        out += glob.glob(f"{PROJECTS}/*/{i}.jsonl")
    return out

# ---------------------------------------------------------------- rendering
TAG_RE = re.compile(r"<system-reminder>.*?</system-reminder>", re.S)

def ts(s: str | None) -> str:
    if not s:
        return ""
    t = datetime.fromisoformat(s.replace("Z", "+00:00")).astimezone(SP)
    return t.strftime("%Y-%m-%d %H:%M")

def title_of(sid: str) -> str:
    return (meta.get(sid) or {}).get("title", sid)

def quote(text: str) -> str:
    return "\n".join("> " + line if line else ">" for line in text.strip().splitlines())

def details(summary: str, body: str) -> str:
    return f"<details><summary>{summary}</summary>\n\n{body.strip()}\n\n</details>\n"

def render_user_text(text: str) -> tuple[str, str] | None:
    """Return (kind, markdown) for a user-role text, or None to skip it."""
    text = TAG_RE.sub("", text).strip()
    if not text:
        return None
    if text.startswith("This session is being continued from a previous conversation"):
        return "event", details("📦 Context compacted: summary of the earlier conversation", text)
    if text.startswith("Base directory for this skill"):
        name = re.search(r"skills/([^/\s]+)", text)
        return "event", details(f"📘 Skill loaded: {name.group(1) if name else 'skill'}", text[:4000])
    m = re.search(r'<cross-session-message[^>]*?(?:from-name|name)="([^"]+)"[^>]*>(.*?)</cross-session-message>', text, re.S)
    if m:
        return "peer", f"**📨 Message from session “{m.group(1)}”**\n\n{quote(m.group(2))}\n"
    if text.startswith(("<side-sessions-event>", "<task-notification>", "<ci-monitor-event>")):
        body = re.sub(r"<[^>]+>", "", text).strip()
        return "event", details("⚙️ App event", body[:3000])
    if "<bash-input>" in text:
        cmd = re.search(r"<bash-input>(.*?)</bash-input>", text, re.S)
        outp = re.search(r"<bash-stdout>(.*?)</bash-stdout>", text, re.S)
        md = f"**🖥️ User ran a shell command**\n\n```bash\n{cmd.group(1).strip() if cmd else ''}\n```\n"
        if outp and outp.group(1).strip():
            md += f"\n```text\n{outp.group(1).strip()[:3000]}\n```\n"
        return "user", md
    if text.startswith(("<bash-stdout>", "<bash-stderr>", "<local-command")):
        return None
    m = re.search(r"<command-name>(.*?)</command-name>", text)
    if m:
        args = re.search(r"<command-args>(.*?)</command-args>", text, re.S)
        return "user", f"`{m.group(1)}` {args.group(1).strip() if args else ''}\n"
    text = re.sub(r"</?pasted_content[^>]*>", "", text).strip()
    if text.startswith("[Request interrupted"):
        return "event", f"_{text}_\n"
    return "user", text + "\n"

def short(v: object, n: int = 160) -> str:
    s = " ".join(str(v).split())
    return s if len(s) <= n else s[: n - 1] + "…"

def render_tool(block: dict) -> str:
    name = block.get("name", "tool")
    inp = block.get("input") or {}
    nice = name.replace("mcp__ccd_session_mgmt__", "").replace("mcp__ccd_session__", "").replace("mcp__ccd_turn__", "")
    if name == "Bash":
        desc = inp.get("description") or ""
        return f"- 🔧 **Bash** — {short(desc)}\n  `{short(inp.get('command', ''), 220)}`"
    if name in ("Read", "Write", "Edit"):
        return f"- 🔧 **{name}** `{short(inp.get('file_path', ''), 200)}`"
    if name == "SendMessage":
        return f"- 📤 **SendMessage** → `{short(inp.get('to', ''), 60)}`: {short(inp.get('message', ''), 400)}"
    if name in ("Agent", "Task"):
        return f"- 🤖 **Subagent** ({inp.get('subagent_type', 'general')}): {short(inp.get('description', ''))}"
    if name.endswith("start_session"):
        return f"- 🚀 **Start session** “{short(inp.get('title', ''), 100)}”: {short(inp.get('prompt', ''), 300)}"
    if name.endswith("update_plan"):
        items = inp.get("items")
        if items:
            return "- 📋 **Plan**: " + "; ".join(short(i.get("content", ""), 60) for i in items)
        return ""
    if name.endswith("wrap_up"):
        return f"- ✅ **Wrap-up**: {short(inp.get('recap', ''), 400)}"
    if name in ("ToolSearch", "ReadNotifications") or name.endswith(("mark_chapter", "read_me")):
        return ""
    key = next((k for k in ("description", "query", "pattern", "url", "title", "prompt", "session_id") if k in inp), None)
    return f"- 🔧 **{nice}**" + (f" — {short(inp[key])}" if key else "")

ALL_SEEN: set[str] = set()

def render_session(files: list[str], brief_from: str | None = None, skip: set[str] | None = None) -> tuple[str, int, str, str]:
    lines: list[str] = []
    turns = 0
    first = last = ""
    seen: set[str] = set()
    for f in sorted(files, key=os.path.getmtime):
        speaker = None
        for raw in open(f):
            try:
                o = json.loads(raw)
            except json.JSONDecodeError:
                continue
            if o.get("isSidechain") or o.get("type") not in ("user", "assistant"):
                continue
            u = o.get("uuid")
            if u in seen or (skip is not None and u in skip):
                continue
            seen.add(u)
            ALL_SEEN.add(u)
            t = o.get("timestamp")
            first = first or t or ""
            last = t or last
            content = (o.get("message") or {}).get("content")
            if o["type"] == "user":
                if o.get("isMeta") or o.get("isCompactSummary") is False and False:
                    continue
                texts = [content] if isinstance(content, str) else [
                    b.get("text", "") for b in (content or []) if isinstance(b, dict) and b.get("type") == "text"
                ]
                for text in texts:
                    r = render_user_text(text)
                    if not r:
                        continue
                    kind, md = r
                    if kind == "user" and brief_from and not any("### " in l for l in lines):
                        lines.append(f"\n---\n\n### 📋 Brief from {brief_from} (start of this session)\n\n{md}")
                        speaker = "user"
                    elif kind == "user":
                        turns += 1
                        lines.append(f"\n---\n\n### 👤 User · {ts(t)}\n\n{md}")
                        speaker = "user"
                    else:
                        lines.append(f"\n{md}")
                        speaker = kind
            else:
                for b in content or []:
                    if not isinstance(b, dict):
                        continue
                    if b.get("type") == "text" and b.get("text", "").strip():
                        if speaker != "assistant":
                            lines.append(f"\n#### 🤖 Claude · {ts(t)}\n")
                            speaker = "assistant"
                        lines.append("\n" + b["text"].strip() + "\n")
                    elif b.get("type") == "tool_use":
                        md = render_tool(b)
                        if md:
                            if speaker != "assistant":
                                lines.append(f"\n#### 🤖 Claude · {ts(t)}\n")
                                speaker = "assistant"
                            lines.append(md)
    return "\n".join(lines), turns, first, last

# ---------------------------------------------------------------- write
os.makedirs(OUT, exist_ok=True)
index_rows: list[str] = []

def prs(o: dict) -> str:
    return ", ".join(f"[#{p['prNumber']}]({p['url']})" for p in o.get("prs") or [])

def export(sid: str, folder: str, prefix: str, depth: int, parent_title: str | None) -> None:
    o = meta[sid]
    files = transcript_files(o)
    is_fork = "fork" in name if (name := (o.get("spawnedFrom") or {}).get("name") or "") else False
    body, turns, first, last = render_session(files, None if is_fork else parent_title, ALL_SEEN if is_fork else None)
    name = (o.get("spawnedFrom") or {}).get("name") or ROOTS.get(sid) or "session"
    fname = f"{prefix}-{re.sub(r'[^a-z0-9-]+', '-', name.lower()).strip('-')}.md"
    path = os.path.join(OUT, folder, fname)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    header = [
        f"# {o.get('title', sid)}",
        "",
        "| | |",
        "|---|---|",
        f"| Session | `{sid}` |",
        f"| Started by | {parent_title or '— (top-level session)'} |",
        f"| Period (São Paulo) | {ts(first)} → {ts(last)} |",
        f"| User turns | {turns} |",
        f"| Worktree / branch | `{o.get('worktreeName') or os.path.basename(o.get('cwd', ''))}` / `{o.get('branch', '')}` |",
        f"| Pull requests | {prs(o) or '—'} |",
        f"| Transcript files | {', '.join('`' + os.path.basename(x) + '`' for x in sorted(files, key=os.path.getmtime)) or 'none found'} |",
        "",
        "Tool results, internal reasoning and system reminders are left out; tool calls are shown as one line each.",
        "",
    ] + (["A fork of the session above: only the messages after the fork point are shown.", ""] if is_fork else [])
    open(path, "w").write("\n".join(header) + body + "\n")
    indent = "  " * depth
    index_rows.append(
        f"{indent}- [{o.get('title', sid)}]({folder}/{fname}) · {ts(first)[:10]} → {ts(last)[:10]} · {turns} user turn{'' if turns == 1 else 's'}"
        + (f" · {prs(o)}" if prs(o) else "")
    )
    for i, c in enumerate(children.get(sid, []), 1):
        export(c, folder, f"{prefix}.{i:02d}", depth + 1, o.get("title"))

sections = {"lead-backend": "Lead Backend", "code-reviewer": "Code reviewer and merge agent", "lead-frontend": "Lead Frontend"}
index = ["# Maravi DI1: AI conversation history", ""]
for sid, folder in ROOTS.items():
    index_rows = []
    export(sid, folder, "00", 0, None)
    index += [f"## {sections[folder]}", "", *index_rows, ""]
    print(folder, len(index_rows), "sessions")

# The project kickoff ran in a terminal, outside the desktop app.
kick = glob.glob(f"{PROJECTS}/*Maravi/{KICKOFF}*.jsonl")
if kick:
    body, turns, first, last = render_session(kick)
    os.makedirs(os.path.join(OUT, "kickoff"), exist_ok=True)
    open(os.path.join(OUT, "kickoff", "00-kickoff.md"), "w").write(
        f"# Project kickoff: specification and planning (terminal)\n\n| | |\n|---|---|\n"
        f"| Period (São Paulo) | {ts(first)} → {ts(last)} |\n| User turns | {turns} |\n"
        f"| Transcript file | `{os.path.basename(kick[0])}` |\n\n"
        "Tool results, internal reasoning and system reminders are left out; tool calls are shown as one line each.\n" + body + "\n"
    )
    index += ["## Before the leads", "", f"- [Project kickoff: specification and planning (terminal)](kickoff/00-kickoff.md) · {ts(first)[:10]} → {ts(last)[:10]} · {turns} user turn{'' if turns == 1 else 's'}", ""]

open(os.path.join(OUT, "README.md"), "w").write("\n".join(index))
print("done")
