"""
WEB DIR MAP - Desktop Backend (standalone Python)
Mapeador recursivo de URLs web (Apache/Nginx "Index of").
Usado pelo wrapper Electron via stdin/stdout JSON.
"""
import os
import sys
import io
import json
import time
import re
import fnmatch
from pathlib import Path
from typing import List, Optional, Dict, Any
from urllib.parse import urljoin, urlparse, unquote

import requests
from bs4 import BeautifulSoup


SENSITIVE_PATTERNS = [
    r"\.env(\..+)?$", r"^\.git", r"wp-config\.php", r"\.sql(\.gz|\.bz2)?$",
    r"\.bak$", r"\.backup$", r"\.old$", r"\.swp$", r"\.swo$",
    r"id_rsa", r"id_dsa", r"\.pem$", r"\.key$", r"\.ppk$",
    r"\.htpasswd", r"\.htaccess", r"config\.(php|json|yml|yaml|ini)$",
    r"credentials", r"secrets?\.", r"\.DS_Store",
    r"dump\.sql", r"database\.sql", r"phpinfo\.php",
    r"composer\.lock", r"package-lock\.json", r"\.npmrc",
    r"web\.config", r"\.aws", r"\.ssh",
]
SENSITIVE_REGEX = [re.compile(p, re.IGNORECASE) for p in SENSITIVE_PATTERNS]


def is_sensitive(name: str) -> bool:
    return any(rx.search(name) for rx in SENSITIVE_REGEX)


DEFAULT_MAX_ITEMS = 100_000
DEFAULT_MAX_DEPTH_HARD = 50
REQUEST_TIMEOUT = 10
USER_AGENT = "Mozilla/5.0 (compatible; WebDirMap-Desktop/1.0)"


class ScanLimitExceeded(Exception):
    pass


def _parse_listing(html: str, base_url: str) -> List[Dict[str, str]]:
    soup = BeautifulSoup(html, "lxml")
    base_parsed = urlparse(base_url)
    base_path = base_parsed.path
    items: List[Dict[str, str]] = []
    seen = set()

    for a in soup.find_all("a", href=True):
        href = a.get("href", "").strip()
        if not href or href.startswith(("?", "#")):
            continue
        if href.lower().startswith(("mailto:", "javascript:", "tel:")):
            continue
        if href in ("../", "..", "/"):
            continue

        absolute = urljoin(base_url, href)
        ap = urlparse(absolute)
        if ap.netloc != base_parsed.netloc:
            continue
        if not ap.path.startswith(base_path) or ap.path == base_path:
            continue

        name = a.get_text(strip=True) or unquote(href)
        if name.lower() in ("parent directory", "..", "../"):
            continue

        is_dir = ap.path.endswith("/")
        segs = [s for s in ap.path.rstrip("/").split("/") if s]
        display = unquote(segs[-1]) if segs else name
        if is_dir:
            display += "/"

        key = (absolute, is_dir)
        if key in seen:
            continue
        seen.add(key)
        items.append({"name": display, "href": absolute, "is_dir": is_dir})

    return items


class WebScanner:
    def __init__(self, hidden_extensions="", hide_files=False, max_depth=None,
                 max_items=DEFAULT_MAX_ITEMS, detect_sensitive=True, query_string="",
                 special_files="", special_dirs="", special_words=""):
        self.hidden_extensions = [e.strip().lower().lstrip(".") for e in hidden_extensions.split(",") if e.strip()]
        self.hide_files = hide_files
        self.max_depth = min(max_depth or DEFAULT_MAX_DEPTH_HARD, DEFAULT_MAX_DEPTH_HARD)
        self.max_items = max_items if max_items and max_items > 0 else DEFAULT_MAX_ITEMS
        self.detect_sensitive = detect_sensitive
        self.query_string = query_string or ""
        self.special_files = self._split_attention(special_files)
        self.special_dirs = self._split_attention(special_dirs)
        self.special_words = self._split_attention(special_words)
        self._items_seen = 0
        self._truncated = False
        self._errors: List[str] = []
        self._sensitive_hits: List[Dict[str, str]] = []
        self._special_hits: List[Dict[str, str]] = []
        self._special_counts = {"file": 0, "extension": 0, "dir": 0, "word": 0}
        self._special_breakdown = {"file": {}, "extension": {}, "dir": {}, "word": {}}
        self._visited: set = set()
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": USER_AGENT})

    def _split_attention(self, value: str) -> List[str]:
        if not value:
            return []
        parts = re.split(r"[\n,;]+", str(value))
        return [p.strip().lower() for p in parts if p.strip()]

    def _attention_match(self, name: str, is_dir: bool) -> Optional[Dict[str, str]]:
        clean = name.rstrip("/")
        low = clean.lower()
        ext = Path(clean).suffix.lower().lstrip(".")

        if is_dir:
            for token in self.special_dirs:
                t = token.rstrip("/").lower()
                if t and (low == t or t in low or fnmatch.fnmatch(low, t)):
                    return {"kind": "dir", "reason": token}
        else:
            for token in self.special_files:
                t = token.lower().lstrip()
                t_no_dot = t.lstrip(".")
                if not t:
                    continue
                if low == t or low.endswith(t) or fnmatch.fnmatch(low, t):
                    return {"kind": "file", "reason": token}
                if ext and ext == t_no_dot and (t.startswith(".") or "." not in t):
                    return {"kind": "extension", "reason": token}

        for token in self.special_words:
            t = token.lower()
            if t and (t in low or fnmatch.fnmatch(low, t)):
                return {"kind": "word", "reason": token}
        return None

    def _should_skip_file(self, name: str) -> bool:
        if self.hide_files:
            return True
        if self.hidden_extensions:
            ext = Path(name).suffix.lower().lstrip(".")
            if ext in self.hidden_extensions:
                return True
        return False

    def _fetch(self, url: str) -> Optional[str]:
        if self.query_string:
            sep = "&" if "?" in url else "?"
            full = f"{url}{sep}{self.query_string.lstrip('?&')}"
        else:
            full = url
        try:
            r = self.session.get(full, timeout=REQUEST_TIMEOUT, allow_redirects=True)
            if r.status_code != 200:
                self._errors.append(f"{r.status_code} {url}")
                return None
            ctype = r.headers.get("Content-Type", "").lower()
            if "html" not in ctype and "text" not in ctype:
                return None
            return r.text
        except requests.RequestException as e:
            self._errors.append(f"{type(e).__name__} {url}")
            return None

    def scan(self, root_url: str) -> Dict[str, Any]:
        self._items_seen = 0
        self._truncated = False
        self._errors = []
        self._sensitive_hits = []
        self._special_hits = []
        self._special_counts = {"file": 0, "extension": 0, "dir": 0, "word": 0}
        self._special_breakdown = {"file": {}, "extension": {}, "dir": {}, "word": {}}
        self._visited = set()

        parsed = urlparse(root_url)
        if not parsed.scheme or not parsed.netloc:
            return {"error": "URL inválida (use http:// ou https://)"}
        if not parsed.path.endswith("/"):
            root_url += "/"

        result = {"name": parsed.netloc + parsed.path, "type": "directory", "url": root_url, "children": []}
        stack = [(root_url, result, 0)]

        try:
            while stack:
                current_url, current_node, depth = stack.pop()
                if depth >= self.max_depth or current_url in self._visited:
                    continue
                self._visited.add(current_url)

                html = self._fetch(current_url)
                if html is None:
                    current_node["error"] = "Sem acesso"
                    continue

                items = _parse_listing(html, current_url)
                items.sort(key=lambda x: (not x["is_dir"], x["name"].lower()))

                for entry in items:
                    if not entry["is_dir"] and self._should_skip_file(entry["name"]):
                        continue
                    self._items_seen += 1
                    if self._items_seen > self.max_items:
                        self._truncated = True
                        raise ScanLimitExceeded()
                    sensitive = self.detect_sensitive and is_sensitive(entry["name"])
                    if sensitive:
                        self._sensitive_hits.append({"name": entry["name"], "url": entry["href"]})
                    special = self._attention_match(entry["name"], entry["is_dir"])
                    if special:
                        self._special_hits.append({"name": entry["name"], "url": entry["href"], **special})
                        kind = special.get("kind")
                        reason = (special.get("reason") or "").strip().lower()
                        if kind in self._special_counts:
                            self._special_counts[kind] += 1
                            if reason:
                                self._special_breakdown[kind][reason] = self._special_breakdown[kind].get(reason, 0) + 1
                    if entry["is_dir"]:
                        child = {"name": entry["name"], "type": "directory", "url": entry["href"],
                                 "sensitive": sensitive, "special": bool(special), "children": []}
                        current_node["children"].append(child)
                        stack.append((entry["href"], child, depth + 1))
                    else:
                        current_node["children"].append({"name": entry["name"], "type": "file",
                                                          "url": entry["href"], "sensitive": sensitive, "special": bool(special)})
        except ScanLimitExceeded:
            pass

        result["_meta"] = {
            "items_seen": self._items_seen, "truncated": self._truncated, "max_items": self.max_items,
            "errors": self._errors[:50], "sensitive_count": len(self._sensitive_hits),
            "sensitive_hits": self._sensitive_hits[:500],
            "special_count": len(self._special_hits), "special_hits": self._special_hits[:500],
            "special_counts": dict(self._special_counts),
            "special_breakdown": {k: dict(v) for k, v in self._special_breakdown.items()},
        }
        return result


def generate_uml(data):
    if "error" in data and "children" not in data:
        return f"Erro: {data['error']}\n"
    lines = []
    meta = data.get("_meta") or {}

    def walk(node, prefix, is_last, is_root):
        name = node.get("name", "root")
        marker = " [!]" if node.get("sensitive") else ""
        marker += " [★]" if node.get("special") else ""
        if is_root:
            lines.append(f"{name}\n")
        else:
            connector = "└── " if is_last else "├── "
            suffix = "" if node.get("type") == "directory" and name.endswith("/") else ("/" if node.get("type") == "directory" else "")
            lines.append(f"{prefix}{connector}{name}{suffix}{marker}\n")
        children = node.get("children", []) or []
        for i, child in enumerate(children):
            walk(child, "" if is_root else prefix + ("    " if is_last else "│   "), i == len(children) - 1, False)

    walk(data, "", True, True)
    if meta.get("truncated"):
        lines.append(f"\n... [TRUNCADO: limite de {meta.get('max_items')} itens]\n")
    if meta.get("sensitive_count"):
        lines.append(f"\n[!] {meta['sensitive_count']} arquivo(s) sensível(is) detectado(s).\n")
    if meta.get("special_count"):
        lines.append(f"\n[★] {meta['special_count']} item(ns) com atenção especial.\n")
    return "".join(lines)


def _strip_meta(node):
    out = {k: v for k, v in node.items() if k != "_meta"}
    if "children" in out and out["children"]:
        out["children"] = [_strip_meta(c) for c in out["children"]]
    return out


def generate_json_str(data):
    return json.dumps(_strip_meta(data), indent=2, ensure_ascii=False)


def generate_diagram(data):
    if "error" in data and "children" not in data:
        return f"Erro: {data['error']}\n"
    lines = []

    def walk(node, level):
        name = node.get("name", "root")
        indent = "  " * level
        bw = max(len(name) + 2, 9)
        lines.append(f"{indent}┌{'─' * bw}┐\n{indent}│{name.center(bw)}│\n{indent}└{'─' * bw}┘\n")
        children = node.get("children", []) or []
        if children:
            lines.append(f"{indent}{' ' * (bw // 2)}│\n")
            for c in children:
                if c.get("type") == "directory":
                    walk(c, level + 1)
                else:
                    marker = " [!]" if c.get("sensitive") else ""
                    marker += " [★]" if c.get("special") else ""
                    lines.append(f"{'  ' * (level + 1)}• {c['name']}{marker}\n")

    walk(data, 0)
    if (data.get("_meta") or {}).get("truncated"):
        lines.append("\n... [TRUNCADO]\n")
    return "".join(lines)


def map_web_api(url, hidden_extensions="", hide_files=False, max_depth=None,
                max_items=None, format_type="uml", detect_sensitive=True, query_string="",
                special_files="", special_dirs="", special_words="") -> str:
    scanner = WebScanner(hidden_extensions, hide_files, max_depth, max_items or DEFAULT_MAX_ITEMS,
                         detect_sensitive, query_string, special_files, special_dirs, special_words)
    started = time.time()
    tree = scanner.scan(url)
    elapsed = int((time.time() - started) * 1000)
    if "error" in tree and "children" not in tree:
        payload = {"content": f"Erro: {tree['error']}", "items": 0, "truncated": False,
                   "elapsed_ms": elapsed, "error": tree["error"], "sensitive_count": 0, "sensitive_hits": [],
                   "special_count": 0, "special_hits": [], "special_counts": {"file": 0, "extension": 0, "dir": 0, "word": 0},
                   "special_breakdown": {"file": {}, "extension": {}, "dir": {}, "word": {}}}
        return json.dumps(payload, ensure_ascii=False)

    ft = (format_type or "uml").lower()
    if ft == "json":
        content = generate_json_str(tree)
    elif ft == "diagram":
        content = generate_diagram(tree)
    else:
        content = generate_uml(tree)

    meta = tree.get("_meta") or {}
    payload = {
        "content": content, "items": meta.get("items_seen", 0),
        "truncated": meta.get("truncated", False), "elapsed_ms": elapsed, "error": None,
        "sensitive_count": meta.get("sensitive_count", 0),
        "sensitive_hits": meta.get("sensitive_hits", []),
        "special_count": meta.get("special_count", 0),
        "special_hits": meta.get("special_hits", []),
        "special_counts": meta.get("special_counts", {"file": 0, "extension": 0, "dir": 0, "word": 0}),
        "special_breakdown": meta.get("special_breakdown", {"file": {}, "extension": {}, "dir": {}, "word": {}}),
    }
    return json.dumps(payload, ensure_ascii=False)


if __name__ == "__main__":
    if hasattr(sys.stdout, "buffer"):
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    if hasattr(sys.stderr, "buffer"):
        sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")
    try:
        raw = sys.stdin.read()
        if not raw.strip():
            print(json.dumps({"error": "Nenhum input"}))
            sys.exit(1)
        d = json.loads(raw)
        out = map_web_api(
            url=d.get("url", ""),
            hidden_extensions=d.get("hidden_extensions", "") or "",
            hide_files=bool(d.get("hide_files", False)),
            max_depth=d.get("max_depth"),
            max_items=d.get("max_items"),
            format_type=d.get("format_type", "uml") or "uml",
            detect_sensitive=bool(d.get("detect_sensitive", True)),
            query_string=d.get("query_string", "") or "",
            special_files=d.get("special_files", "") or "",
            special_dirs=d.get("special_dirs", "") or "",
            special_words=d.get("special_words", "") or "",
        )
        sys.stdout.write(out)
        sys.stdout.flush()
    except Exception as e:
        sys.stderr.write(f"ERRO: {e}\n")
        sys.exit(2)
