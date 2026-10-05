#!/usr/bin/env python3
"""Add and validate releases in the chunkzero mise registry."""

import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
import urllib.request

ROOT = Path(__file__).resolve().parent.parent
TOOLS = ROOT / "tools"
NUMBER = r"(?:0|[1-9][0-9]*)"
VERSION = re.compile(rf"{NUMBER}\.{NUMBER}\.{NUMBER}(?:-(?:(?:alpha|beta|rc)\.{NUMBER}|nightly\.[0-9]{{14}}\.g[0-9a-f]{{12}}))?")
REPOSITORY = re.compile(r"[A-Za-z0-9-]+/[A-Za-z0-9._-]+")
ZERO = "0" * 40
PLATFORMS = {"linux-x64", "linux-arm64", "darwin-x64", "darwin-arm64", "windows-x64"}


def channel(version):
    if "-nightly." in version:
        return "nightly"
    return "beta" if "-" in version else "latest"


def precedence(version):
    """Semantic version precedence key; a release sorts after its prereleases."""
    core, _, prerelease = version.partition("-")
    identifiers = [(0, int(part), "") if part.isdigit() else (1, 0, part) for part in prerelease.split(".")]
    return tuple(map(int, core.split("."))), not prerelease, identifiers


def load(tool):
    return json.loads((TOOLS / f"{tool}.json").read_text())


def save(tool, registry):
    (TOOLS / f"{tool}.json").write_text(json.dumps(registry, indent=2) + "\n")


def errors_in(tool, registry):
    errors = []
    repository = registry.get("repository", "")
    if not REPOSITORY.fullmatch(repository):
        errors.append(f"{tool}: repository must be owner/name, not {repository!r}")
    versions = [entry.get("version", "") for entry in registry.get("versions", [])]
    if all(map(VERSION.fullmatch, versions)) and versions != sorted(versions, key=precedence):
        errors.append(f"{tool}: versions must be listed oldest to newest")
    seen = set()
    for entry in registry.get("versions", []):
        version = entry.get("version", "")
        if not VERSION.fullmatch(version):
            errors.append(f"{tool}: invalid version {version!r}")
            continue
        if version in seen:
            errors.append(f"{tool}: duplicate version {version}")
        seen.add(version)
        if entry.get("tag") != f"v{version}" or set(entry) != {"version", "tag", "assets"}:
            errors.append(f"{tool} {version}: entries need exactly version, tag v{version} and assets")
        assets = entry.get("assets") or {}
        if not assets or not set(assets) <= PLATFORMS:
            errors.append(f"{tool} {version}: assets must cover known platforms {sorted(PLATFORMS)}")
        for platform, asset in assets.items():
            url = (f"https://github.com/{repository}/releases/download/v{version}/"
                   f"{tool}-{version}-{platform}.tar.gz")
            if asset.get("url") != url or not re.fullmatch(r"[0-9a-f]{64}", asset.get("sha256", "")):
                errors.append(f"{tool} {version} {platform}: expected url {url} and a sha256")
    for name in {channel(version) for version in seen} - set(registry.get("channels", {})):
        errors.append(f"{tool}: channel {name} is missing")
    for name, version in registry.get("channels", {}).items():
        if name not in {"latest", "beta", "nightly"} or version not in seen or channel(version) != name:
            errors.append(f"{tool}: channel {name} must point at a registered {name} version, not {version}")
        elif any(channel(other) == name and precedence(other) > precedence(version) for other in seen):
            errors.append(f"{tool}: channel {name} does not point at the newest {name} version")
    return errors


def add(tool, entry):
    registry = load(tool)
    existing = next((item for item in registry["versions"] if item["version"] == entry["version"]), None)
    if existing is not None:
        if existing != entry:
            raise SystemExit(f"{tool} {entry['version']} is already registered with different contents")
        return
    registry["versions"].append(entry)
    registry["versions"].sort(key=lambda item: precedence(item["version"]))
    name = channel(entry["version"])
    current = registry["channels"].get(name)
    if current is None or precedence(entry["version"]) > precedence(current):
        registry["channels"][name] = entry["version"]
    errors = errors_in(tool, registry)
    if errors:
        raise SystemExit("\n".join(errors))
    save(tool, registry)


def git(*args):
    return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True, check=True).stdout


def at_base(base):
    """Every tool's registry at `base`; an all-zero base (a branch's first push) has none."""
    if base == ZERO:
        return {}
    git("cat-file", "-e", f"{base}^{{commit}}")
    paths = git("ls-tree", "--name-only", base, "tools/").split()
    return {Path(path).stem: json.loads(git("show", f"{base}:{path}")) for path in paths if path.endswith(".json")}


def download_sha256(url):
    digest = hashlib.sha256()
    with urllib.request.urlopen(url, timeout=120) as response:
        while chunk := response.read(1 << 20):
            digest.update(chunk)
    return digest.hexdigest()


def check(base):
    errors = []
    registries = {path.stem: json.loads(path.read_text()) for path in sorted(TOOLS.glob("*.json"))}
    for tool, registry in registries.items():
        errors += errors_in(tool, registry)
    if base is None:
        return errors
    for tool, before in at_base(base).items():
        after = registries.get(tool, {})
        if after.get("repository") != before["repository"]:
            errors.append(f"{tool}: the repository can't change or be removed")
        current = {entry["version"]: entry for entry in after.get("versions", [])}
        for entry in before["versions"]:
            if current.get(entry["version"]) != entry:
                errors.append(f"{tool} {entry['version']}: published entries can't change or be removed")
    if errors:
        return errors
    previous = {(tool, entry["version"]) for tool, before in at_base(base).items() for entry in before["versions"]}
    for tool, registry in registries.items():
        for entry in registry["versions"]:
            if (tool, entry["version"]) in previous:
                continue
            for platform, asset in entry["assets"].items():
                if download_sha256(asset["url"]) != asset["sha256"]:
                    errors.append(f"{tool} {entry['version']} {platform}: downloaded archive doesn't match its sha256")
    return errors


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    add_command = commands.add_parser("add", help="register a release entry and move its channel")
    add_command.add_argument("tool")
    add_command.add_argument("entry", type=Path)
    check_command = commands.add_parser("check", help="validate every tool; with --base, also immutability and archives")
    check_command.add_argument("--base")
    args = parser.parse_args()
    if args.command == "add":
        add(args.tool, json.loads(args.entry.read_text()))
        return
    errors = check(args.base)
    if errors:
        print("\n".join(errors), file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
