"""Check wheel/sdist metadata and resources without importing NetBox."""

import argparse
import tarfile
import zipfile
from email.parser import BytesParser
from pathlib import Path

from release_notes import read_version


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dist-dir", type=Path, default=Path("dist"))
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    version = read_version(root / "netbox_monitoring/version.py")
    wheels = list(args.dist_dir.glob("*.whl"))
    sources = list(args.dist_dir.glob("*.tar.gz"))
    if len(wheels) != 1 or len(sources) != 1:
        raise SystemExit("Expected exactly one wheel and one source archive in the distribution directory.")
    resources = [
        path.relative_to(root)
        for path in (root / "netbox_monitoring").rglob("*")
        if path.is_file() and path.suffix in (".py", ".html", ".js")
    ]
    with zipfile.ZipFile(wheels[0]) as wheel, tarfile.open(sources[0]) as source:
        metadata_path = next(name for name in wheel.namelist() if name.endswith(".dist-info/METADATA"))
        prefix = source.getnames()[0].split("/")[0]
        for metadata in (wheel.read(metadata_path), source.extractfile(f"{prefix}/PKG-INFO").read()):
            fields = BytesParser().parsebytes(metadata)
            if fields["Name"] != "netbox-monitoring" or fields["Version"] != version:
                raise SystemExit("Distribution name/version does not match the source package.")
        for path in resources:
            expected = (root / path).read_bytes()
            if wheel.read(path.as_posix()) != expected:
                raise SystemExit(f"Wheel resource differs from source: {path}")
            if source.extractfile(f"{prefix}/{path.as_posix()}").read() != expected:
                raise SystemExit(f"Source archive resource differs from checkout: {path}")
        for name in (
            "LICENSE",
            "README.md",
            "CHANGELOG.md",
            "COMPATIBILITY.md",
            "RELEASING.md",
            "scripts/release_notes.py",
        ):
            source.getmember(f"{prefix}/{name}")
    print(f"Validated netbox-monitoring {version}: wheel/sdist metadata and {len(resources)} runtime resources.")


if __name__ == "__main__":
    main()
