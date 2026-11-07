"""Install the /fomo hook into an existing desk tree. Does not restart or send."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
HASHES = json.loads((ROOT / "desk_patch" / "hashes.json").read_text(encoding="utf-8"))
ORIGINAL = HASHES["telegram.py"]["original"]
PATCHED = HASHES["telegram.py"]["patched"]
DIFF = ROOT / "desk_patch" / "telegram.py.diff"
PACKAGES = ("fomo_controls", "fomo_oneshot")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Install the inactive /fomo menu into a desk checkout.")
    parser.add_argument("--desk", type=Path, required=True)
    parser.add_argument("--apply", action="store_true", help="Write files. Without this, only print the plan.")
    args = parser.parse_args(argv)
    desk = args.desk.resolve()
    try:
        plan = _plan(desk)
    except InstallError as exc:
        print(f"stopped: {exc}")
        return 2
    for line in plan.lines:
        print(line)
    if not args.apply:
        print("dry-run: no files written, no process restarted, no Telegram call")
        return 0
    if plan.already:
        print("already installed: telegram.py left unchanged")
        _copy_packages(desk)
        print("packages checked, no restart")
        return 0
    backup = _backup(desk / "telegram.py")
    print(f"backup: {backup.name}")
    patched = _apply_diff(desk / "telegram.py")
    digest = _sha256(patched)
    if digest != PATCHED:
        patched.unlink(missing_ok=True)
        print("stopped: patched telegram.py hash mismatch; original left in place via backup")
        return 2
    (desk / "telegram.py").write_bytes(patched.read_bytes())
    patched.unlink(missing_ok=True)
    _copy_packages(desk)
    print("installed: restart the existing desk process yourself when ready; this installer did not restart it or send a message")
    return 0


class InstallError(Exception):
    pass


class _Plan:
    def __init__(self):
        self.lines: list[str] = []
        self.already = False


def _plan(desk: Path) -> _Plan:
    if not desk.is_dir():
        raise InstallError("desk directory is missing")
    telegram = desk / "telegram.py"
    if not telegram.is_file():
        raise InstallError("telegram.py is missing")
    digest = _sha256(telegram)
    plan = _Plan()
    if digest == PATCHED:
        plan.already = True
        plan.lines.append("telegram.py already has the /fomo hook")
    elif digest != ORIGINAL:
        raise InstallError("telegram.py hash does not match the expected desk source; no write")
    else:
        plan.lines.append("telegram.py hash matches the expected desk source")
        plan.lines.append("would backup telegram.py then apply the /fomo hook")
    for name in PACKAGES:
        src = _package_source(name)
        dest = desk / name
        if dest.exists() and not dest.is_dir():
            raise InstallError(f"{name} exists and is not a directory; no write")
        plan.lines.append(f"would copy package {name}" if not dest.exists() else f"would update package {name} only where bytes differ")
    for forbidden in ("settings.json", "secrets", "data", "web"):
        plan.lines.append(f"will not modify {forbidden}")
    return plan


def _backup(path: Path) -> Path:
    stem = path.name + ".bak-" + ORIGINAL[:12]
    dest = path.with_name(stem)
    if dest.exists():
        dest = path.with_name(stem + "-2")
    shutil.copy2(path, dest)
    return dest


def _apply_diff(original: Path) -> Path:
    out = original.with_name("telegram.py.fomo-new")
    if out.exists():
        out.unlink()
    result = subprocess.run(
        ["patch", "--batch", "-o", str(out), "-i", str(DIFF), str(original)],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0 or not out.is_file():
        out.unlink(missing_ok=True)
        raise InstallError("patch did not apply; no write")
    return out


def _copy_packages(desk: Path) -> None:
    for name in PACKAGES:
        src = _package_source(name)
        dest = desk / name
        for path in src.rglob("*"):
            if not path.is_file():
                continue
            if "__pycache__" in path.parts or path.suffix == ".pyc":
                continue
            relative = path.relative_to(src)
            target = dest / relative
            if _forbidden(target, desk):
                raise InstallError("refusing to write a protected desk path")
            target.parent.mkdir(parents=True, exist_ok=True)
            data = path.read_bytes()
            if target.is_file() and target.read_bytes() == data:
                continue
            target.write_bytes(data)


def _package_source(name: str) -> Path:
    if name == "fomo_controls":
        return ROOT
    return ROOT.parent / "fomo_oneshot"


def _forbidden(target: Path, desk: Path) -> bool:
    try:
        relative = target.resolve().relative_to(desk.resolve())
    except ValueError:
        return True
    parts = relative.parts
    if not parts:
        return True
    if parts[0] in {"secrets", "data", "web"}:
        return True
    if relative.name in {"settings.json", "state.json", "activity.json", "chart.json"}:
        return True
    if relative.suffix in {".db", ".sqlite", ".sqlite3"}:
        return True
    return False


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


if __name__ == "__main__":
    sys.exit(main())
