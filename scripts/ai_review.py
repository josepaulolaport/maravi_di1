"""Single-shot AI review of a pull request (CI job ai-review).

Usage: python3 scripts/ai_review.py <base_sha> <head_sha> <out_dir>

Environment: GEMINI_API_KEY; GITHUB_TOKEN, GITHUB_REPOSITORY and PR_NUMBER to post the review;
AI_REVIEW_DRY_RUN=1 writes review.json without posting.

The diff (merge base to head) is sent to Gemini with .github/ai-review/prompt.md, normally in one
request. A diff larger than one request is split by file, then by hunk, into at most
MAX_REQUESTS requests; whatever does not fit is listed as not reviewed. Gemini answers in strict
JSON-schema mode. The merged answer is validated against .github/ai-review/review.schema.json,
written to <out_dir>/review.json and posted as one GitHub review: one inline comment per finding,
on its lines when they are in the diff, otherwise in the review body. Standard library only.
"""

from __future__ import annotations

import copy
import http.client
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
PROMPT = ROOT / ".github/ai-review/prompt.md"
SCHEMA = ROOT / ".github/ai-review/review.schema.json"
ENDPOINT = "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions"
MODEL = "gemini-3.8-flash"
CHUNK_CHARS = 300_000  # about 75k tokens of diff per request
MAX_REQUESTS = 6
REQUEST_TIMEOUT = 180  # seconds; a slower answer is dropped and retried
ATTEMPTS = 3
EXCLUDE = ["backend/uv.lock", "frontend/package-lock.json", "docs"]
# Keywords Gemini's structured output does not document; they are still checked locally.
_UNSUPPORTED = {"$schema", "minLength"}
_TYPES: dict[str, tuple[type, ...]] = {
    "object": (dict,),
    "array": (list,),
    "string": (str,),
    "integer": (int,),
    "number": (int, float),
    "boolean": (bool,),
}


@dataclass
class FileDiff:
    path: str
    header: str
    hunks: list[str] = field(default_factory=list)
    lines: list[set[int]] = field(default_factory=list)  # commentable new lines, per hunk


def parse_diff(diff: str) -> list[FileDiff]:
    """Split a unified diff by file and prefix every new-file line with its line number."""
    files: list[FileDiff] = []
    current: FileDiff | None = None
    new_line = 0
    for raw in diff.splitlines():
        if raw.startswith("diff --git "):
            current = None
        elif raw.startswith("+++ "):
            target = raw[4:]
            current = None if target == "/dev/null" else FileDiff(target.removeprefix("b/"), "")
            if current is not None:
                current.header = f"+++ b/{current.path}"
                files.append(current)
        elif current is None:
            continue
        elif raw.startswith("@@"):
            new_line = int(raw.split("+", 1)[1].split(" ", 1)[0].split(",", 1)[0])
            current.hunks.append(raw + "\n")
            current.lines.append(set())
        elif current.hunks and raw[:1] in (" ", "+"):
            current.hunks[-1] += f"{new_line:>6} {raw}\n"
            current.lines[-1].add(new_line)
            new_line += 1
        elif current.hunks and raw[:1] == "-":
            current.hunks[-1] += f"{'':>6} {raw}\n"
    return [f for f in files if f.hunks]


def chunk(files: list[FileDiff], limit: int) -> list[str]:
    """Pack file pieces into request-sized texts; a piece is a hunk, or a slice of a huge one."""
    pieces: list[str] = []
    for f in files:
        room = limit - len(f.header) - 1
        for hunk in f.hunks:
            for start in range(0, len(hunk), room):
                pieces.append(f"{f.header}\n{hunk[start : start + room]}")
    chunks: list[str] = []
    for piece in pieces:
        if chunks and len(chunks[-1]) + len(piece) <= limit:
            chunks[-1] += piece
        else:
            chunks.append(piece)
    return chunks


def violations(value: Any, schema: dict[str, Any], where: str = "$") -> list[str]:
    """Check the keywords review.schema.json uses."""
    expected = schema.get("type")
    if expected is not None:
        ok = isinstance(value, _TYPES[expected])
        if expected in ("integer", "number") and isinstance(value, bool):
            ok = False
        if not ok:
            return [f"{where}: expected {expected}, got {json.dumps(value)}"]
    if "enum" in schema and value not in schema["enum"]:
        return [f"{where}: {json.dumps(value)} is not one of {schema['enum']}"]
    found: list[str] = []
    if isinstance(value, dict):
        properties = schema.get("properties", {})
        found += [f"{where}: missing {k!r}" for k in schema.get("required", []) if k not in value]
        if schema.get("additionalProperties") is False:
            found += [f"{where}: unexpected {k!r}" for k in value if k not in properties]
        for key, sub in properties.items():
            if key in value:
                found += violations(value[key], sub, f"{where}.{key}")
    if isinstance(value, list) and "items" in schema:
        for n, item in enumerate(value):
            found += violations(item, schema["items"], f"{where}[{n}]")
    if isinstance(value, int | float) and not isinstance(value, bool):
        if "minimum" in schema and value < schema["minimum"]:
            found.append(f"{where}: {value} is below {schema['minimum']}")
        if "maximum" in schema and value > schema["maximum"]:
            found.append(f"{where}: {value} is above {schema['maximum']}")
    if isinstance(value, str) and len(value) < schema.get("minLength", 0):
        found.append(f"{where}: shorter than {schema['minLength']} characters")
    return found


def request_schema(schema: Any) -> Any:
    if isinstance(schema, dict):
        return {k: request_schema(v) for k, v in schema.items() if k not in _UNSUPPORTED}
    if isinstance(schema, list):
        return [request_schema(v) for v in schema]
    return copy.deepcopy(schema)


def http_json(
    url: str, payload: dict[str, Any], headers: dict[str, str], *, idempotent: bool = False
) -> Any:
    """POST JSON; retry 429 and 5xx with Retry-After or a growing wait, then fail loudly.

    An idempotent call (the Gemini request) is also retried when the connection drops or times
    out; posting the review is not, since a lost response may still have created it.
    """
    body = json.dumps(payload).encode()
    for attempt in range(1, ATTEMPTS + 1):
        request = urllib.request.Request(
            url, body, {"Content-Type": "application/json", **headers}, method="POST"
        )
        started = time.monotonic()
        try:
            with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT) as response:
                return json.load(response)
        except urllib.error.HTTPError as error:
            detail = error.read().decode(errors="replace")[:2000]
            if (error.code == 429 or error.code >= 500) and attempt < ATTEMPTS:
                retry_after = error.headers.get("Retry-After", "")
                wait = int(retry_after) if retry_after.isdigit() else 30 * attempt
                sys.stderr.write(f"HTTP {error.code}, retry {attempt} in {wait}s: {detail}\n")
                time.sleep(wait)
                continue
            raise RuntimeError(f"HTTP {error.code} from {url}: {detail}") from error
        except (http.client.HTTPException, urllib.error.URLError, OSError) as error:
            elapsed = time.monotonic() - started
            if not idempotent or attempt == ATTEMPTS:
                raise RuntimeError(f"{url}: {error!r} after {elapsed:.0f}s") from error
            sys.stderr.write(f"{error!r} after {elapsed:.0f}s, retry {attempt} in 10s\n")
            time.sleep(10)
    raise AssertionError("unreachable")


def ask_gemini(prompt: str, diff_text: str, part: str, schema: dict[str, Any]) -> Any:
    payload = {
        "model": MODEL,
        "temperature": 0,
        # Gemini 3 cannot turn thinking off; its default level kept a ~10k-token diff waiting
        # until the connection was dropped after 280 s.
        "reasoning_effort": "low",
        "messages": [
            {"role": "system", "content": prompt},
            {"role": "user", "content": f"Pull request diff ({part}):\n\n{diff_text}"},
        ],
        "response_format": {
            "type": "json_schema",
            "json_schema": {"name": "review", "schema": request_schema(schema), "strict": True},
        },
    }
    key = os.environ["GEMINI_API_KEY"]
    started = time.monotonic()
    answer = http_json(ENDPOINT, payload, {"Authorization": f"Bearer {key}"}, idempotent=True)
    usage = answer.get("usage", {})
    sys.stdout.write(
        f"{part}: {len(diff_text)} chars, {time.monotonic() - started:.0f}s, "
        f"tokens in={usage.get('prompt_tokens')} out={usage.get('completion_tokens')}\n"
    )
    return json.loads(answer["choices"][0]["message"]["content"])


def anchor(finding: dict[str, Any], files: dict[str, FileDiff]) -> dict[str, Any] | None:
    """GitHub accepts a comment only on lines of one hunk of the diff."""
    diff = files.get(finding["file"])
    if diff is None:
        return None
    start, end = finding["start_line"], finding["end_line"]
    for lines in diff.lines:
        if end in lines:
            comment: dict[str, Any] = {"path": diff.path, "line": end, "side": "RIGHT"}
            if start < end and start in lines:
                comment |= {"start_line": start, "start_side": "RIGHT"}
            return comment
    return None


def comment_body(finding: dict[str, Any]) -> str:
    severity, confidence = finding["severity"], finding["confidence"]
    text = f"**{severity}** · confidence {confidence:.2f}\n\n{finding['issue']}"
    if finding["suggestion"]:
        fence = "````" if "```" in finding["suggestion"] else "```"
        text += f"\n\n**Suggestion**\n\n{fence}\n{finding['suggestion']}\n{fence}"
    return text


def post_review(review: dict[str, Any], files: dict[str, FileDiff], head: str, notes: str) -> None:
    comments, loose = [], []
    for finding in review["findings"]:
        place = anchor(finding, files)
        if place:
            comments.append(place | {"body": comment_body(finding)})
        else:
            where = f"`{finding['file']}` lines {finding['start_line']}-{finding['end_line']}"
            loose.append(f"- {where}: {comment_body(finding)}")
    body = f"### AI review ({MODEL})\n\n{review['summary']}\n\n{notes}" + "\n".join(loose)
    url = (
        f"https://api.github.com/repos/{os.environ['GITHUB_REPOSITORY']}"
        f"/pulls/{os.environ['PR_NUMBER']}/reviews"
    )
    headers = {
        "Authorization": f"Bearer {os.environ['GITHUB_TOKEN']}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    payload = {"commit_id": head, "event": "COMMENT", "body": body, "comments": comments}
    http_json(url, payload, headers)
    sys.stdout.write(f"posted {len(comments)} inline comment(s), {len(loose)} in the body\n")


def main(base: str, head: str, out_dir: str) -> int:
    pathspec = [".", *(f":(exclude){p}" for p in EXCLUDE)]
    diff = subprocess.run(
        ["git", "diff", "--no-color", "--unified=3", "-M", f"{base}...{head}", "--", *pathspec],
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    files = parse_diff(diff)
    chunks = chunk(files, CHUNK_CHARS)
    reviewed, skipped = chunks[:MAX_REQUESTS], chunks[MAX_REQUESTS:]
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    prompt = PROMPT.read_text(encoding="utf-8")

    summaries: list[str] = []
    findings: list[Any] = []
    for n, text in enumerate(reviewed, start=1):
        answer = ask_gemini(prompt, text, f"part {n} of {len(reviewed)}", schema)
        summaries.append(str(answer.get("summary", "")))
        findings += answer.get("findings") or []
    review = {
        "summary": summaries[0] if len(summaries) == 1 else " ".join(summaries),
        "findings": findings,
    }
    if not reviewed:
        review["summary"] = "No reviewable changes."
    notes = ""
    if skipped:
        names = sorted({ln[6:] for c in skipped for ln in c.splitlines() if ln[:6] == "+++ b/"})
        missed = ", ".join(names)
        notes = f"**Not reviewed, in whole or in part** (diff too large): {missed}\n\n"
        sys.stderr.write(
            f"::warning title=ai-review::not reviewed, in whole or in part: {missed}\n"
        )

    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    (out / "review.json").write_text(json.dumps(review, indent=2) + "\n", encoding="utf-8")
    problems = violations(review, schema)
    for problem in problems:
        sys.stderr.write(f"::error title=ai-review schema::{problem}\n")
    sys.stdout.write(
        f"{len(files)} file(s) in {len(reviewed)} request(s); {len(findings)} finding(s); "
        f"{len(problems)} schema violation(s)\n"
    )
    if summary_file := os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(summary_file, "a", encoding="utf-8") as handle:
            handle.write(f"### AI review\n\n{review['summary']}\n\n{notes}")
            handle.write(f"{len(findings)} finding(s); review.json is in the ai-review artifact\n")
    if problems:
        return 1
    if os.environ.get("AI_REVIEW_DRY_RUN") != "1" and (findings or skipped):
        post_review(review, {f.path: f for f in files}, head, notes)
    return 0


if __name__ == "__main__":
    if len(sys.argv) != 4:
        raise SystemExit(__doc__)
    raise SystemExit(main(*sys.argv[1:]))
