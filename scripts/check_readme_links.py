#!/usr/bin/env python3
import pathlib
import re

FILES = [
    "README.md",
    "README_CN.md",
    "INSTALL.md",
    "INSTALL_CN.md",
    "backend/README.md",
    "frontend/README.md",
    "deploy/README.md",
    # new deploy docs split from deploy/README
    "deploy/TROUBLESHOOTING.md",
    "deploy/DATABASE.md",
    "deploy/SERVICE_MANAGEMENT.md",
    "deploy/ADVANCED_BUILD.md",
]

LINK_RE = re.compile(r"\]\(([^)]+)\)")


def iter_links(text: str):
    for m in LINK_RE.finditer(text):
        yield m.group(1)


def is_external(url: str) -> bool:
    return url.startswith(("http://", "https://", "#", "mailto:"))


def main() -> int:
    missing: dict[str, list[str]] = {}

    for f in FILES:
        fp = pathlib.Path(f)
        if not fp.exists():
            missing[f] = ["<file missing>"]
            continue

        text = fp.read_text(encoding="utf-8")

        bad: set[str] = set()
        for url in iter_links(text):
            if is_external(url):
                continue

            if url.startswith("./"):
                url = url[2:]

            url = url.split("#", 1)[0]
            if not url:
                continue

            # only check relative paths (md or directory-like)
            if url.endswith(".md") or "/" in url:
                target = (fp.parent / url).resolve()
                if not target.exists():
                    bad.add(url)

        if bad:
            missing[f] = sorted(bad)

    print("missing link targets:")
    if not missing:
        print("none")
    else:
        for f, bad in missing.items():
            print(f"- {f}: {', '.join(bad)}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())