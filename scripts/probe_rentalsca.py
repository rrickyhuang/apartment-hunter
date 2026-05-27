"""One-off probe to confirm rentals.ca listings can be parsed from HTML."""
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from apartment_hunter.http_client import get


def extract_json_after(html: str, marker_pattern: str) -> dict:
    m = re.search(marker_pattern, html)
    if not m:
        raise RuntimeError("marker not found")
    start = m.end() - 1  # position of opening '{'
    depth = 0
    in_str = False
    esc = False
    i = start
    while i < len(html):
        c = html[i]
        if in_str:
            if esc:
                esc = False
            elif c == "\\":
                esc = True
            elif c == '"':
                in_str = False
        else:
            if c == '"':
                in_str = True
            elif c == "{":
                depth += 1
            elif c == "}":
                depth -= 1
                if depth == 0:
                    return json.loads(html[start : i + 1])
        i += 1
    raise RuntimeError("unbalanced braces")


def main():
    seen_ids: set[str] = set()
    for p in [1, 2, 3]:
        r = get(f"https://rentals.ca/vancouver?page={p}")
        data = extract_json_after(r.text, r"response:\s*(\{)")
        edges = data["data"]["edges"]
        page_ids = {e["node"]["id"] for e in edges}
        new = page_ids - seen_ids
        print(
            f"page {p}: status={r.status_code} edges={len(edges)} "
            f"new={len(new)} hasNext={data['data']['pageInfo']['hasNextPage']}"
        )
        seen_ids |= page_ids
    print("total unique across 3 pages:", len(seen_ids))


if __name__ == "__main__":
    main()
