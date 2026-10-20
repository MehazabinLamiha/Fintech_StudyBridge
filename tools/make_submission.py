#!/usr/bin/env python3
"""Build a clean submission zip of this repository.

Finder's "Compress" adds __MACOSX/ and ._ resource files, .DS_Store, __pycache__, the .git folder and var/ (local
audit logs and state). This script zips only the files git tracks or would track (so .gitignore applies), skips
that junk even if it slipped in, and puts everything under one top folder.

    python tools/make_submission.py                       # writes ../StudyBridge-submission.zip
    python tools/make_submission.py --out some/path.zip
"""
import argparse
import subprocess
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
JUNK_PARTS = {"__MACOSX", "__pycache__", ".git", ".DS_Store", "var"}


def keep(path: str) -> bool:
    """True for a file that belongs in the submission."""
    parts = Path(path).parts
    name = parts[-1] if parts else ""
    return bool(parts) and not (set(parts) & JUNK_PARTS) and not name.startswith("._") and not name.endswith(".pyc")


def files() -> list:
    out = subprocess.run(["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"], cwd=ROOT,
                         check=True, capture_output=True).stdout.decode()
    return sorted(p for p in out.split("\0") if p and keep(p) and (ROOT / p).is_file())


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--out", default=str(ROOT.parent / "StudyBridge-submission.zip"))
    ap.add_argument("--top", default=ROOT.name, help="folder name inside the zip")
    args = ap.parse_args(argv)
    names = files()
    with zipfile.ZipFile(args.out, "w", zipfile.ZIP_DEFLATED) as z:
        for p in names:
            z.write(ROOT / p, f"{args.top}/{p}")
    print(f"{len(names)} files -> {args.out}")


if __name__ == "__main__":
    sys.exit(main())
