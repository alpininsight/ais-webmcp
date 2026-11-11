# SPDX-License-Identifier: Apache-2.0
"""Exercise actual bundle validation with real wheel/sdist files, no network."""

import copy
import hashlib
import importlib.util
import io
import json
import tarfile
import zipfile
from pathlib import Path, PureWindowsPath

import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "bundle_publication", ROOT / "scripts/check_publication.py"
)
publication = importlib.util.module_from_spec(spec)
spec.loader.exec_module(publication)
SHA = "a" * 40
VERSION = "1.2.3"


def distribution(path, *, name="ais-webmcp", version=VERSION):
    data = f"Metadata-Version: 2.1\nName: {name}\nVersion: {version}\n\n".encode()
    if path.name.endswith(".whl"):
        with zipfile.ZipFile(path, "w") as archive:
            archive.writestr(f"ais_webmcp-{version}.dist-info/METADATA", data)
    else:
        with tarfile.open(path, "w:gz") as archive:
            info = tarfile.TarInfo(f"ais_webmcp-{version}/PKG-INFO")
            info.size = len(data)
            archive.addfile(info, io.BytesIO(data))


def inventory(bundle):
    paths = sorted([*bundle.joinpath("dist").iterdir(), *bundle.joinpath("cdn").iterdir()])
    data = {
        "source_sha": SHA,
        "version": VERSION,
        "source_dirty": False,
        "cdn_prefix": "ais-webmcp",
        "files": [
            {
                "path": path.relative_to(bundle).as_posix(),
                "size": path.stat().st_size,
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            }
            for path in paths
            if path.name != "inventory.json"
        ],
    }
    write_inventory(bundle, data)
    return data


def write_inventory(bundle, data):
    (bundle / "cdn/inventory.json").write_text(json.dumps(data))


@pytest.fixture
def bundle(tmp_path):
    root = tmp_path / "bundle"
    (root / "dist").mkdir(parents=True)
    (root / "cdn").mkdir()
    distribution(root / f"dist/ais_webmcp-{VERSION}-py3-none-any.whl")
    distribution(root / f"dist/ais_webmcp-{VERSION}.tar.gz")
    (root / "cdn/register.js").write_bytes(b"reviewed runtime\n")
    (root / "cdn/webmcp-manifest.schema.json").write_bytes(b'{"type":"object"}\n')
    inventory(root)
    return root


def test_real_wheel_sdist_bundle_passes(bundle):
    publication.verify_bundle(bundle, SHA, VERSION)


def test_posix_inventory_stays_valid_with_windows_path_parsing(bundle, monkeypatch):
    # Emulate native Windows parsing without requiring a Windows filesystem.
    # Inventory entries remain POSIX strings on every supported platform.
    monkeypatch.setattr(publication, "Path", PureWindowsPath)
    publication.verify_bundle(bundle, SHA, VERSION)


def test_contradictory_second_wheel_identity_is_rejected(bundle):
    wheel = bundle / f"dist/ais_webmcp-{VERSION}-py3-none-any.whl"
    with zipfile.ZipFile(wheel, "a") as archive:
        archive.writestr(
            "other_project-9.9.9.dist-info/METADATA",
            b"Name: other-project\nVersion: 9.9.9\n\n",
        )
    inventory(bundle)
    with pytest.raises(ValueError, match="wheel metadata"):
        publication.verify_bundle(bundle, SHA, VERSION)


@pytest.mark.parametrize(
    "member",
    [
        f"nested/ais_webmcp-{VERSION}.dist-info/METADATA",
        "ais_webmcp-9.9.9.dist-info/METADATA",
    ],
)
def test_single_wheel_metadata_member_must_have_canonical_project_path(bundle, member):
    wheel = bundle / f"dist/ais_webmcp-{VERSION}-py3-none-any.whl"
    with zipfile.ZipFile(wheel, "w") as archive:
        archive.writestr(member, f"Name: ais-webmcp\nVersion: {VERSION}\n\n")
    inventory(bundle)
    with pytest.raises(ValueError, match="wheel metadata"):
        publication.verify_bundle(bundle, SHA, VERSION)


def test_duplicate_canonical_wheel_metadata_is_rejected(bundle):
    wheel = bundle / f"dist/ais_webmcp-{VERSION}-py3-none-any.whl"
    with zipfile.ZipFile(wheel, "a") as archive:
        with pytest.warns(UserWarning, match="Duplicate name"):
            archive.writestr(
                f"ais_webmcp-{VERSION}.dist-info/METADATA",
                f"Name: ais-webmcp\nVersion: {VERSION}\n\n",
            )
    inventory(bundle)
    with pytest.raises(ValueError, match="wheel metadata"):
        publication.verify_bundle(bundle, SHA, VERSION)


@pytest.mark.parametrize("kind", ["wheel", "sdist"])
def test_two_artifacts_of_same_kind_are_not_wheel_and_sdist(bundle, kind):
    if kind == "wheel":
        (bundle / f"dist/ais_webmcp-{VERSION}.tar.gz").unlink()
        distribution(bundle / f"dist/ais_webmcp-{VERSION}-py2-none-any.whl")
    else:
        (bundle / f"dist/ais_webmcp-{VERSION}-py3-none-any.whl").unlink()
        distribution(bundle / f"dist/ais_webmcp-{VERSION}-second.tar.gz")
    inventory(bundle)
    with pytest.raises(ValueError):
        publication.verify_bundle(bundle, SHA, VERSION)


@pytest.mark.parametrize("directory", ["dist", "cdn"])
def test_parent_directory_symlink_cannot_hide_valid_external_bytes(bundle, directory):
    outside = bundle.parent / f"external-{directory}"
    (bundle / directory).rename(outside)
    (bundle / directory).symlink_to(outside, target_is_directory=True)
    with pytest.raises(ValueError, match="symlink"):
        publication.verify_bundle(bundle, SHA, VERSION)


def test_bundle_root_symlink_is_rejected(bundle):
    alias = bundle.parent / "bundle-alias"
    alias.symlink_to(bundle, target_is_directory=True)
    with pytest.raises(ValueError, match="symlink"):
        publication.verify_bundle(alias, SHA, VERSION)


@pytest.mark.parametrize(
    "field,value",
    [("source_sha", "b" * 40), ("version", "9.9.9"), ("source_dirty", True)],
)
def test_wrong_provenance_is_rejected(bundle, field, value):
    data = json.loads((bundle / "cdn/inventory.json").read_text())
    data[field] = value
    write_inventory(bundle, data)
    with pytest.raises(ValueError, match="provenance"):
        publication.verify_bundle(bundle, SHA, VERSION)


@pytest.mark.parametrize("field,value", [("size", 0), ("sha256", "0" * 64)])
def test_wrong_recorded_size_or_hash_is_rejected(bundle, field, value):
    data = json.loads((bundle / "cdn/inventory.json").read_text())
    data["files"][0][field] = value
    write_inventory(bundle, data)
    with pytest.raises(ValueError, match="checksum"):
        publication.verify_bundle(bundle, SHA, VERSION)


@pytest.mark.parametrize(
    "path", ["../external", "/absolute", "other/register.js", "dist\\runtime.whl"]
)
def test_inventory_cannot_escape_closed_namespaces(bundle, path):
    data = json.loads((bundle / "cdn/inventory.json").read_text())
    data["files"][0]["path"] = path
    write_inventory(bundle, data)
    with pytest.raises(ValueError, match="inventory path"):
        publication.verify_bundle(bundle, SHA, VERSION)


@pytest.mark.parametrize("metadata", [{"name": "other-project"}, {"version": "9.9.9"}])
def test_distribution_metadata_identity_is_required(bundle, metadata):
    wheel = bundle / f"dist/ais_webmcp-{VERSION}-py3-none-any.whl"
    with zipfile.ZipFile(wheel, "w") as archive:
        archive.writestr(
            f"ais_webmcp-{VERSION}.dist-info/METADATA",
            f"Name: {metadata.get('name', 'ais-webmcp')}\n"
            f"Version: {metadata.get('version', VERSION)}\n\n",
        )
    inventory(bundle)
    with pytest.raises(ValueError, match="names or versions"):
        publication.verify_bundle(bundle, SHA, VERSION)


def test_duplicate_inventory_entry_is_rejected(bundle):
    data = json.loads((bundle / "cdn/inventory.json").read_text())
    data["files"].append(copy.deepcopy(data["files"][0]))
    write_inventory(bundle, data)
    with pytest.raises(ValueError, match="inventory"):
        publication.verify_bundle(bundle, SHA, VERSION)


def test_extra_distribution_is_rejected(bundle):
    (bundle / "dist/unrecorded.whl").write_bytes(b"not inventoried")
    with pytest.raises(ValueError, match="inventory"):
        publication.verify_bundle(bundle, SHA, VERSION)


def test_unrecorded_cdn_file_is_rejected(bundle):
    (bundle / "cdn/unreviewed.js").write_bytes(b"not inventoried")
    with pytest.raises(ValueError, match="inventory"):
        publication.verify_bundle(bundle, SHA, VERSION)
