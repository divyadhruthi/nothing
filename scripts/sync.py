#!/usr/bin/env python3
"""Fetch public portfolio data. Writes each destination only after a valid response."""
from datetime import datetime, timezone
from pathlib import Path
from base64 import b64decode
import argparse, json, os, re, sys, urllib.error, urllib.request
from html import escape, unescape
from urllib.parse import quote

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
CONFIG = json.loads((Path(__file__).parent / "config.json").read_text(encoding="utf-8-sig"))
GITHUB_USER = CONFIG["github_username"]
LEETCODE_USER = CONFIG["leetcode_username"]
GFG_URL = CONFIG["gfg_profile_url"]
NOW = lambda: datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")

def request(url, headers=None, data=None):
    h = {"User-Agent": "KishorePortfolioSync/1.0", "Accept": "application/json"}
    h.update(headers or {})
    req = urllib.request.Request(url, data=data, headers=h)
    with urllib.request.urlopen(req, timeout=35) as response:
        return response.read()

def save(name, payload):
    payload["lastSynced"] = NOW()
    path = DATA / name
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    temp.replace(path)
    print(f"Updated {path.relative_to(ROOT)}")

def readme_overview(markdown):
    """Return the first useful prose paragraph from a README, capped at 160 chars."""
    paragraphs, list_items = [], []
    current, current_is_list = [], False
    in_fence = False

    def flush():
        nonlocal current, current_is_list
        if current:
            text = " ".join(current).strip()
            if current_is_list:
                list_items.append(text)
            else:
                paragraphs.append(text)
        current, current_is_list = [], False

    for raw_line in markdown.splitlines():
        line = raw_line.strip()
        if line.startswith(("```", "~~~")):
            flush()
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        if not line or line.startswith("#") or "![" in line or "shields.io" in line:
            flush()
            continue
        if re.fullmatch(r"(?:[-*_]\s*){3,}", line):
            flush()
            continue

        line = re.sub(r"<br\s*/?>", " ", line, flags=re.I)
        line = re.sub(r"<[^>]*>", " ", line)
        line = unescape(line).strip()
        line = re.sub(r"^>\s*", "", line)
        is_list = bool(re.match(r"^(?:[-*+]\s+|\d+[.)]\s+)", line))
        if is_list:
            line = re.sub(r"^(?:[-*+]\s+|\d+[.)]\s+)", "", line)
        if not line or line.startswith("|"):
            flush()
            continue
        if current and current_is_list != is_list:
            flush()
        current_is_list = is_list
        current.append(line)
    flush()

    def clean(text):
        text = re.sub(r"!\[[^\]]*\]\([^)]*\)", " ", text)
        text = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", text)
        text = re.sub(r"\[([^\]]+)\]\[[^\]]*\]", r"\1", text)
        text = re.sub(r"`+([^`]+)`+", r"\1", text)
        text = re.sub(r"(?:\*\*|__|~~|\*|_)", "", text)
        text = re.sub(r"<[^>]*>", " ", text)
        return re.sub(r"\s+", " ", unescape(text)).strip()

    for paragraph in paragraphs:
        text = clean(paragraph)
        if len(text) >= 40:
            return shorten_overview(text)

    # Lists are a last resort; ordinary prose always takes precedence.
    candidates = [clean(item) for item in list_items]
    for text in candidates:
        if len(text) >= 40 and not re.match(r"(?i)^(?:install|installation|npm\s|pnpm\s|yarn\s|bun\s|pip\s|git clone|docker\s)", text):
            return shorten_overview(text)
    return shorten_overview(candidates[0]) if candidates and candidates[0] else ""

def shorten_overview(text):
    if len(text) <= 160:
        return text
    shortened = text[:159]
    if " " in shortened:
        shortened = shortened.rsplit(" ", 1)[0]
    return shortened.rstrip(" ,;:-") + "…"

def norm(value):
    return re.sub(r"[^a-z0-9]", "", str(value or "").casefold())

def load_json(name, default):
    try:
        return json.loads((DATA / name).read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return default

def curated_sync_summary(current_repo_names):
    """Report which curated entries in data/projects.json match a synced public repo."""
    config = load_json("projects.json", {})
    current = {norm(name) for name in current_repo_names}
    matched, hidden = [], []
    for entry in config.get("projects", []):
        name = str(entry.get("name") or entry.get("repo") or "")
        repo = str(entry.get("repo") or name).strip()
        if norm(repo) in current:
            matched.append(f"{name} -> {repo}")
        elif entry.get("alwaysShow"):
            matched.append(f"{name} (alwaysShow)")
        else:
            hidden.append(f"{name} -> {repo or '(no repo)'}")
    return matched, hidden

def sync_github():
    headers = {}
    token = os.getenv("GITHUB_TOKEN")
    if token: headers["Authorization"] = f"Bearer {token}"
    raw = request(f"https://api.github.com/users/{GITHUB_USER}/repos?type=public&sort=updated&per_page=100", headers)
    repos = json.loads(raw)
    if not isinstance(repos, list): raise ValueError("GitHub response was not a repository list")
    cache = {}
    try:
        previous = json.loads((DATA / "github.json").read_text(encoding="utf-8"))
        previous_repos = previous if isinstance(previous, list) else previous.get("repos", [])
        cache = {str(r.get("name", "")).casefold(): r for r in previous_repos if isinstance(r, dict)}
    except (OSError, ValueError, TypeError):
        pass

    synced_repos = []
    excluded = {"fork": [], "archived": [], "portfolio-hidden": [], "private": []}
    for repo in repos:
        if not isinstance(repo, dict):
            continue
        topics = repo.get("topics") or []
        reasons = []
        if repo.get("fork"):
            reasons.append("fork")
        if repo.get("archived"):
            reasons.append("archived")
        if repo.get("private"):
            reasons.append("private")
        if any(str(topic).casefold() == "portfolio-hidden" for topic in topics):
            reasons.append("portfolio-hidden")
        for reason in reasons:
            excluded[reason].append(str(repo.get("name") or "(unnamed repo)"))
        if reasons:
            continue

        item = {k: repo.get(k) for k in ("name", "description", "html_url", "homepage", "language", "topics", "stargazers_count", "updated_at", "pushed_at")}
        name = str(repo.get("name", ""))
        old = cache.get(name.casefold(), {})
        pushed_at = repo.get("pushed_at")
        overview = old.get("overview", "")
        readme_sha = old.get("readmeSha")
        readme_pushed_at = old.get("readmePushedAt")

        # The repo-list endpoint has pushed_at, not a README blob SHA. Use it to
        # avoid README requests on unchanged repositories, then compare the actual
        # README SHA when a repository has changed.
        if not (pushed_at and readme_pushed_at == pushed_at and "overview" in old):
            url = f"https://api.github.com/repos/{quote(GITHUB_USER, safe='')}/{quote(name, safe='')}/readme"
            try:
                readme = json.loads(request(url, headers))
                new_sha = readme.get("sha")
                if new_sha and new_sha == readme_sha:
                    overview = old.get("overview", "")
                else:
                    content = readme.get("content", "")
                    if readme.get("encoding") == "base64" and content:
                        markdown = b64decode(content).decode("utf-8", "replace")
                        overview = readme_overview(markdown)
                    else:
                        overview = ""
                readme_sha = new_sha or readme_sha
                readme_pushed_at = pushed_at
            except urllib.error.HTTPError as exc:
                if exc.code == 404:
                    # Cache a confirmed missing README until the next repository push.
                    readme_pushed_at = pushed_at
                print(f"README sync skipped for {name}: {exc}", file=sys.stderr)
            except Exception as exc:
                # Keep the last good overview and retry on the next scheduled run.
                print(f"README sync skipped for {name}: {exc}", file=sys.stderr)

        item["overview"] = overview
        item["readmeSha"] = readme_sha
        item["readmePushedAt"] = readme_pushed_at
        synced_repos.append(item)

    # The API response is authoritative. Only cached README metadata for repos
    # still present in this successful response is copied into the new file.
    save("github.json", {"repos": synced_repos})
    print(f"GitHub repos returned: {len(repos)}")
    for reason, names in excluded.items():
        print(f"Excluded ({reason}): {len(names)}" + (f" — {', '.join(names)}" if names else ""))
    print(f"GitHub repos written: {len(synced_repos)}")
    matched, hidden = curated_sync_summary(item.get("name", "") for item in synced_repos)
    print(f"Curated entries matched: {', '.join(matched) if matched else 'none'}")
    print(f"Curated entries hidden: {', '.join(hidden) if hidden else 'none'}")

def sync_leetcode():
    year = datetime.now(timezone.utc).year
    query = '''query userPortfolio($username: String!) {
      matchedUser(username: $username) {
        username
        submitStats { acSubmissionNum { difficulty count submissions } }
        profile { ranking reputation }
        userCalendar(year: YEAR) { activeYears streak totalActiveDays submissionCalendar }
        previousCalendar: userCalendar(year: PREVIOUS_YEAR) { submissionCalendar }
      }
      recentAcSubmissionList(username: $username, limit: 15) { title titleSlug timestamp }
    }'''
    query = query.replace("PREVIOUS_YEAR", str(year - 1)).replace("YEAR", str(year))
    body = json.dumps({"query": query, "variables": {"username": LEETCODE_USER}}).encode()
    result = json.loads(request("https://leetcode.com/graphql", {"Content-Type": "application/json", "Referer": "https://leetcode.com"}, body))
    user = result.get("data", {}).get("matchedUser")
    if not user: raise ValueError("LeetCode did not return a matched user")
    profile = user.get("profile") or {}
    calendar = user.get("userCalendar") or {}
    merged_calendar = {}
    for source in (user.get("previousCalendar") or {}, calendar):
        raw_calendar = source.get("submissionCalendar") or "{}"
        try: merged_calendar.update(json.loads(raw_calendar) if isinstance(raw_calendar, str) else raw_calendar)
        except (TypeError, ValueError): pass
    calendar["submissionCalendar"] = json.dumps(merged_calendar)
    save("leetcode.json", {"username": LEETCODE_USER, "submitStats": user.get("submitStats") or {}, "profile": profile, "ranking": profile.get("ranking"), "reputation": profile.get("reputation"), "calendar": calendar, "recentAccepted": result.get("data", {}).get("recentAcSubmissionList") or []})


def sync_gfg():
    # Best-effort parser for public profile data embedded in the rendered GFG page.
    html = request(GFG_URL, {"Accept": "text/html,application/xhtml+xml"}).decode("utf-8", "replace")
    # Keys appear as "key": or \"key\": in embedded JSON. Requiring the opening quote stops
    # "score" from matching "monthly_score" or "total_score".
    def key_pattern(name):
        return r'\\?"' + re.escape(name) + r'\\?"\s*:\s*(\d+)'
    marker = re.search(key_pattern("total_problems_solved"), html)
    if not marker:
        raise ValueError("Could not recognize GFG profile statistics; preserving previous file")
    snippet = html[max(0, marker.start() - 1200):marker.end() + 200]
    def field(name):
        found = re.search(key_pattern(name), snippet)
        return int(found.group(1)) if found else None
    save("gfg.json", {"profileUrl": GFG_URL, "problemsSolved": int(marker.group(1)), "codingScore": field("score"), "instituteRank": field("institute_rank"), "difficulty": {}})

# --- Static fallback HTML -------------------------------------------------------------
# index.html contains <!-- generated:NAME:start --> ... <!-- generated:NAME:end --> blocks.
# They are rebuilt from the JSON files so crawlers, link previews, no-JS visitors and failed
# fetches see the same data the page would load. The page's JavaScript replaces them at runtime.

PROFILE_GITHUB = f"https://github.com/{GITHUB_USER}"
PROFILE_LEETCODE = f"https://leetcode.com/u/{LEETCODE_USER}/"

def e(value):
    return escape(str(value if value is not None else ""), quote=True)

def safe_url(url):
    url = str(url or "").strip()
    return url if re.match(r"(?i)^https?://", url) else ""

def readable_repo_name(name):
    text = re.sub(r"[-_]+", " ", str(name or "")).strip().title()
    return re.sub(r"\b(Ai|Api|Ui|Ux|Ml|Sql|Css|Html|Js|Ts)\b", lambda m: m.group(0).upper(), text)

def project_tags(repo):
    labels = {"react": "React", "python": "Python", "javascript": "JavaScript", "typescript": "TypeScript", "firebase": "Firebase", "fastapi": "FastAPI"}
    tags = []
    for raw in [*(repo.get("topics") or []), repo.get("language")]:
        if not raw:
            continue
        low = str(raw).casefold()
        tag = next((v for k, v in labels.items() if k in low), "JavaScript" if low == "js" else str(raw))
        if tag not in tags:
            tags.append(tag)
    return tags

def display_date(iso):
    try:
        d = datetime.fromisoformat(str(iso).replace("Z", "+00:00"))
    except ValueError:
        return ""
    return f"{d:%b} {d.day}, {d.year}"

def portfolio_projects():
    """Same selection rules as loadProjects() in index.html."""
    config = load_json("projects.json", {})
    github = load_json("github.json", {})
    repos = github if isinstance(github, list) else github.get("repos", [])
    by_key = {norm(r.get("name")): r for r in repos if isinstance(r, dict)}
    topic = str(config.get("extraTopic") or "portfolio").casefold()
    used, result = set(), []
    for c in config.get("projects", []):
        key = norm(c.get("repo") or c.get("name"))
        repo = by_key.get(key)
        if not repo and not c.get("alwaysShow"):
            continue
        if repo:
            used.add(key)
        repo = repo or {}
        result.append({
            "name": c.get("name") or readable_repo_name(repo.get("name")),
            "summary": c.get("description") or repo.get("overview") or repo.get("description") or "",
            "tags": list(c.get("tags") or project_tags(repo)),
            "outcome": c.get("outcome") or "",
            "homepage": c.get("homepage") or repo.get("homepage") or "",
            "html_url": c.get("html_url") or repo.get("html_url") or "",
        })
    extras = [r for k, r in by_key.items() if k not in used and any(str(t).casefold() == topic for t in r.get("topics") or [])]
    extras.sort(key=lambda r: str(r.get("pushed_at") or r.get("updated_at") or ""), reverse=True)
    for r in extras:
        result.append({"name": readable_repo_name(r.get("name")), "summary": r.get("overview") or r.get("description") or "",
                       "tags": project_tags(r), "outcome": "", "homepage": r.get("homepage") or "", "html_url": r.get("html_url") or ""})
    return result

def render_projects():
    cards = []
    for p in portfolio_projects():
        live, repo = safe_url(p["homepage"]), safe_url(p["html_url"])
        links = (f'<a href="{e(live)}" target="_blank" rel="noopener">Live ↗</a>' if live else "") + (
            f'<a href="{e(repo)}" target="_blank" rel="noopener">GitHub ↗</a>' if repo
            else f'<a href="{e(PROFILE_GITHUB)}" target="_blank" rel="noopener">GitHub profile ↗</a>')
        cards.append(
            f'\n<article class="card project"><h3>{e(p["name"])}</h3>'
            + (f'<p class="projectDescription">{e(p["summary"])}</p>' if p["summary"] else "")
            + '<div class="tags">' + "".join(f'<span class="tag">{e(t)}</span>' for t in p["tags"]) + "</div>"
            + (f'<p class="projectOutcome">{e(p["outcome"])}</p>' if p["outcome"] else "")
            + f'<div class="projectLinks">{links}</div></article>')
    return "".join(cards) + "\n" if cards else '<div class="card empty">Projects will appear here once they are public on GitHub.</div>'

def profile_button(url):
    return f'<a class="btn secondary" target="_blank" rel="noopener" href="{e(url)}">View profile ↗</a>'

def stat(value, label):
    return f'<div class="stat"><strong>{e(value)}</strong><span>{e(label)}</span></div>'

def render_leetcode():
    d = load_json("leetcode.json", {})
    if not d.get("lastSynced"):
        return f'<div class="sync">Profile stats will appear after the first successful sync.</div><div class="profileBody">{profile_button(PROFILE_LEETCODE)}</div>'
    counts = {str(x.get("difficulty", "")).casefold(): int(x.get("count") or 0) for x in (d.get("submitStats") or {}).get("acSubmissionNum", [])}
    cal = d.get("calendar") or {}
    return (f'<div class="sync">Synced {e(display_date(d["lastSynced"]))}</div><div class="profileBody">'
            f'<div class="profileStats">{stat(counts.get("all", 0), "Problems solved")}{stat(int(cal.get("totalActiveDays") or 0), "Active days")}{stat(str(int(cal.get("streak") or 0)) + " days", "Current streak")}</div>'
            f'<div class="profileSnapshot"><span>Easy {counts.get("easy", 0)}</span><span>Medium {counts.get("medium", 0)}</span><span>Hard {counts.get("hard", 0)}</span></div>'
            f'{profile_button(PROFILE_LEETCODE)}</div>')

def render_gfg():
    d = load_json("gfg.json", {})
    if not d.get("lastSynced"):
        return f'<div class="sync">Profile stats will appear after the first successful sync.</div><div class="profileBody">{profile_button(GFG_URL)}</div>'
    return (f'<div class="sync">Synced {e(display_date(d["lastSynced"]))}</div><div class="profileBody">'
            f'<div class="profileStats gfgStats">{stat(int(d.get("problemsSolved") or 0), "Problems solved")}{stat(int(d.get("codingScore") or 0), "Coding score")}</div>'
            f'{profile_button(d.get("profileUrl") or GFG_URL)}</div>')

def render_static():
    path = ROOT / "index.html"
    html = path.read_text(encoding="utf-8")
    original = html
    for name, render in (("projects", render_projects), ("leetcode", render_leetcode), ("gfg", render_gfg)):
        start, end = f"<!-- generated:{name}:start -->", f"<!-- generated:{name}:end -->"
        if html.count(start) != 1 or html.count(end) != 1:
            print(f"::warning::index.html is missing the {name} markers; static fallback not updated")
            continue
        i, j = html.index(start) + len(start), html.index(end)
        html = html[:i] + render() + html[j:]
    if html != original:
        temp = path.with_suffix(".html.tmp")
        temp.write_text(html, encoding="utf-8", newline="\n")
        temp.replace(path)
        print("Updated index.html static fallback")
    else:
        print("index.html static fallback already current")

if __name__ == "__main__":
    DATA.mkdir(exist_ok=True)
    parser = argparse.ArgumentParser()
    parser.add_argument("--profiles-only", action="store_true", help="sync LeetCode and GFG only")
    parser.add_argument("--render-only", action="store_true", help="skip network calls; rebuild the static HTML from data/*.json")
    args = parser.parse_args()
    failed = []
    jobs = () if args.render_only else (sync_leetcode, sync_gfg) if args.profiles_only else (sync_github, sync_leetcode, sync_gfg)
    for job in jobs:
        try: job()
        except Exception as exc:
            failed.append(job.__name__)
            # ::warning:: shows as an annotation on the Actions run summary.
            print(f"::warning::{job.__name__} failed; existing data retained: {exc}")
    # Always rebuild the fallback so whatever did sync reaches the static HTML.
    render_static()
    if failed:
        print(f"Failed jobs: {', '.join(failed)}", file=sys.stderr)
        sys.exit(1)


