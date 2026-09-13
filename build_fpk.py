#!/usr/bin/env python3
"""Build an fnOS .fpk package from the fn-music-rebuild source directory."""
import io
import os
import tarfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
PKG_DIR = ROOT / "fn-music-rebuild"
APP_DIR = PKG_DIR / "app"
MANIFEST = PKG_DIR / "manifest"


def get_manifest_info() -> dict[str, str]:
    info = {}
    for line in MANIFEST.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, val = line.split("=", 1)
        info[key.strip()] = val.strip()
    return info


def make_app_tgz(app_dir: Path) -> bytes:
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as tar:
        for path in sorted(app_dir.rglob("*")):
            rel = path.relative_to(PKG_DIR).as_posix()
            tarinfo = tar.gettarinfo(str(path), arcname=rel)
            if path.is_file():
                tarinfo.mode = 0o644
                with path.open("rb") as f:
                    tar.addfile(tarinfo, f)
            elif path.is_dir():
                tarinfo.mode = 0o755
                tar.addfile(tarinfo)
    return buffer.getvalue()


def build_fpk(output_path: Path | None = None) -> Path:
    meta = get_manifest_info()
    appname = meta.get("appname", "fn-music-rebuild")
    version = meta.get("version", "0.3.0")
    if output_path is None:
        output_path = ROOT / f"{appname}-v{version}.fpk"

    app_tgz_bytes = make_app_tgz(APP_DIR)

    with tarfile.open(output_path, mode="w") as fpk:
        # 1. Add app.tgz
        tinfo = tarfile.TarInfo(name="app.tgz")
        tinfo.size = len(app_tgz_bytes)
        tinfo.mode = 0o644
        fpk.addfile(tinfo, io.BytesIO(app_tgz_bytes))

        # 2. Add other items: cmd, config, wizard, manifest, ICONs
        items = ["cmd", "config", "ICON.PNG", "ICON_256.PNG", "manifest", "wizard"]
        for item in items:
            p = PKG_DIR / item
            if not p.exists():
                continue
            if p.is_file():
                ti = fpk.gettarinfo(str(p), arcname=item)
                ti.mode = 0o755 if "cmd" in item or item == "manifest" else 0o644
                with p.open("rb") as f:
                    fpk.addfile(ti, f)
            elif p.is_dir():
                ti = fpk.gettarinfo(str(p), arcname=item)
                ti.mode = 0o755
                fpk.addfile(ti)
                for sub in sorted(p.rglob("*")):
                    rel = sub.relative_to(PKG_DIR).as_posix()
                    sti = fpk.gettarinfo(str(sub), arcname=rel)
                    if sub.is_file():
                        sti.mode = 0o755 if "cmd" in rel else 0o644
                        with sub.open("rb") as sf:
                            fpk.addfile(sti, sf)
                    elif sub.is_dir():
                        sti.mode = 0o755
                        fpk.addfile(sti)

    print(f"Package built successfully: {output_path.name} ({output_path.stat().st_size} bytes)")
    return output_path


if __name__ == "__main__":
    build_fpk()
