"""Install the work-to-chores / do-chores skills and their cloud pair into the personal hub."""
from __future__ import annotations

import shutil
from pathlib import Path


# Every skill install_skills copies: the 2.2 pair, then the cloud pair.
SKILL_DIRS = ("work-to-chores", "do-chores", "work-to-chores-cloud", "do-chores-cloud")

# Cloud mode: (skill folder, neutral instruction file stem).
CLOUD_COPILOT_FILES = (
    ("work-to-chores-cloud", "plan-work"),
    ("do-chores-cloud", "do-work"),
)


def write_copilot_instructions(
    root: Path, skills: Path | None, mode: str = "openspec"
) -> list[str]:
    written: list[str] = []
    if skills is None:
        return written
    dest_dir = root / ".github" / "instructions"
    dest_dir.mkdir(parents=True, exist_ok=True)
    if mode == "cloud":
        pairs = CLOUD_COPILOT_FILES
    else:
        pairs = tuple((n, n) for n in ("work-to-chores", "do-chores"))
    for name, stem in pairs:
        body = skills / name / "SKILL.md"
        wrapper = skills / name / "SKILL.copilot.md"
        if not body.is_file():
            if mode == "cloud":
                print(f"NOTE missing skill {name}; Copilot file not written")
            continue
        dest = dest_dir / f"{stem}.instructions.md"
        if wrapper.is_file():
            dest.write_text(
                wrapper.read_text(encoding="utf-8") + "\n" + body.read_text(encoding="utf-8"),
                encoding="utf-8",
            )
        else:
            dest.write_text(
                "---\napplyTo: \"**\"\n---\n\n" + body.read_text(encoding="utf-8"),
                encoding="utf-8",
            )
        written.append(str(dest.relative_to(root)))
    return written


def _copy_skill_dir(src: Path, dest: Path) -> None:
    dest.mkdir(parents=True, exist_ok=True)
    for item in src.iterdir():
        target = dest / item.name
        if item.is_dir():
            if target.exists():
                shutil.rmtree(target)
            shutil.copytree(item, target)
        else:
            shutil.copy2(item, target)


def _bridge_skill(hub_skill: Path, dest_parent: Path, name: str, *, force: bool, dry_run: bool) -> None:
    dest = dest_parent / name
    if dry_run:
        print(f"would bridge {dest} -> {hub_skill}")
        return
    dest_parent.mkdir(parents=True, exist_ok=True)
    if dest.exists() or dest.is_symlink():
        if dest.is_symlink() or force:
            if dest.is_symlink() or dest.is_file():
                dest.unlink()
            else:
                shutil.rmtree(dest)
        else:
            print(f"skip bridge {dest} (real directory; pass --force)")
            return
    dest.symlink_to(hub_skill)


def install_skills(
    skills: Path | None,
    error_type: type[Exception],
    *,
    force: bool = False,
    dry_run: bool = False,
    cursor: bool = True,
    claude: bool = True,
) -> int:
    if skills is None:
        raise error_type("skills not found; reinstall w2c (curl install.sh or pipx)")
    hub = Path.home() / ".agents" / "skills"
    for name in SKILL_DIRS:
        skill_src = skills / name
        skill_md = skill_src / "SKILL.md"
        if not skill_md.is_file():
            raise error_type(f"missing {skill_md}")
        dest = hub / name
        if dry_run:
            print(f"would copy {skill_src} -> {dest}")
        elif dest.exists() and not force:
            print(f"exists {dest} (pass --force to replace)")
        else:
            if dest.exists():
                shutil.rmtree(dest)
            _copy_skill_dir(skill_src, dest)
            print(f"installed {dest}")
        if cursor:
            _bridge_skill(dest, Path.home() / ".cursor" / "skills", name, force=force, dry_run=dry_run)
        if claude:
            _bridge_skill(dest, Path.home() / ".claude" / "skills", name, force=force, dry_run=dry_run)
    return 0
