#!/usr/bin/env python3
"""Build script for packaging RACHEL into standalone portable archives using python-build-standalone."""

import argparse
import os
import shutil
import sys
import tarfile
import urllib.request
import zipfile
from pathlib import Path

# python-build-standalone releases
# Reference release tag: 20240107 or recent CPython 3.12 release
PYTHON_BUILD_TAG = "20240107"
PYTHON_VERSION = "3.12.1"

TARGETS = {
    "win-x64": f"cpython-{PYTHON_VERSION}+{PYTHON_BUILD_TAG}-x86_64-pc-windows-msvc-shared-install_only.tar.gz",
    "mac-arm64": f"cpython-{PYTHON_VERSION}+{PYTHON_BUILD_TAG}-aarch64-apple-darwin-install_only.tar.gz",
    "mac-x64": f"cpython-{PYTHON_VERSION}+{PYTHON_BUILD_TAG}-x86_64-apple-darwin-install_only.tar.gz",
    "linux-x64": f"cpython-{PYTHON_VERSION}+{PYTHON_BUILD_TAG}-x86_64-unknown-linux-gnu-install_only.tar.gz",
}

BASE_DOWNLOAD_URL = f"https://github.com/indygreg/python-build-standalone/releases/download/{PYTHON_BUILD_TAG}"

ROOT_DIR = Path(__file__).resolve().parent.parent
DIST_DIR = ROOT_DIR / "dist"
BUILD_DIR = ROOT_DIR / "build"


def get_version() -> str:
    pyproject = ROOT_DIR / "pyproject.toml"
    if pyproject.exists():
        for line in pyproject.read_text(encoding="utf-8").splitlines():
            if line.strip().startswith("version ="):
                return line.split("=")[1].strip().strip('"').strip("'")
    return "0.2.0"


def download_python_runtime(target: str, dest_dir: Path) -> Path:
    filename = TARGETS[target]
    url = f"{BASE_DOWNLOAD_URL}/{filename}"
    archive_path = dest_dir / filename

    if not archive_path.exists():
        print(f"[{target}] Downloading Python runtime from {url}...")
        dest_dir.mkdir(parents=True, exist_ok=True)
        urllib.request.urlretrieve(url, archive_path)
    else:
        print(f"[{target}] Using cached Python runtime archive: {archive_path}")

    return archive_path


def extract_python_runtime(archive_path: Path, target_dir: Path) -> None:
    print(f"Extracting {archive_path.name} to {target_dir}...")
    target_dir.mkdir(parents=True, exist_ok=True)
    with tarfile.open(archive_path, "r:gz") as tar:
        tar.extractall(path=target_dir)


def bundle_target(target: str, version: str) -> Path:
    print(f"\n==================================================")
    print(f"Building standalone bundle for {target} (v{version})...")
    print(f"==================================================")

    target_build_dir = BUILD_DIR / f"rachel-proxy-{target}"
    if target_build_dir.exists():
        shutil.rmtree(target_build_dir)

    python_archive = download_python_runtime(target, BUILD_DIR / "cache")
    extract_python_runtime(python_archive, target_build_dir)

    # Copy application source files into bundle
    app_dest = target_build_dir / "rachel-proxy"
    app_dest.mkdir(parents=True, exist_ok=True)

    for item in ["src", "configs.yaml", "LICENSE", "README.md", "pyproject.toml"]:
        src_path = ROOT_DIR / item
        if src_path.is_dir():
            shutil.copytree(src_path, app_dest / item)
        elif src_path.is_file():
            shutil.copy2(src_path, app_dest / item)

    # Copy launchers
    launchers_dest = app_dest / "launchers"
    launchers_dest.mkdir(parents=True, exist_ok=True)

    if target.startswith("win"):
        win_launcher = ROOT_DIR / "launchers" / "windows" / "launch.bat"
        if win_launcher.exists():
            shutil.copy2(win_launcher, app_dest / "launch.bat")
    elif target.startswith("mac"):
        mac_launcher = ROOT_DIR / "launchers" / "macos" / "launch.command"
        if mac_launcher.exists():
            shutil.copy2(mac_launcher, app_dest / "launch.command")
    elif target.startswith("linux"):
        linux_sh = ROOT_DIR / "launchers" / "linux" / "launch.sh"
        linux_desktop = ROOT_DIR / "launchers" / "linux" / "rachel-proxy.desktop"
        if linux_sh.exists():
            shutil.copy2(linux_sh, app_dest / "launch.sh")
        if linux_desktop.exists():
            shutil.copy2(linux_desktop, app_dest / "rachel-proxy.desktop")

    # Create zip archive in DIST_DIR
    DIST_DIR.mkdir(parents=True, exist_ok=True)
    zip_filename = f"rachel-proxy-v{version}-{target}.zip"
    zip_path = DIST_DIR / zip_filename

    print(f"Creating release zip: {zip_path}...")
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for root, _, files in os.walk(target_build_dir):
            for file in files:
                full_path = Path(root) / file
                rel_path = full_path.relative_to(target_build_dir)
                zf.write(full_path, rel_path)

    print(f"Successfully created: {zip_path}")
    return zip_path


def main():
    parser = argparse.ArgumentParser(description="Build portable Python bundles for RACHEL.")
    parser.add_argument(
        "--target",
        choices=list(TARGETS.keys()) + ["all"],
        default="all",
        help="Target platform bundle to build.",
    )
    args = parser.parse_args()

    version = get_version()
    targets_to_build = list(TARGETS.keys()) if args.target == "all" else [args.target]

    for t in targets_to_build:
        bundle_target(t, version)


if __name__ == "__main__":
    main()
