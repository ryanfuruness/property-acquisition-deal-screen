"""The pipeline can read a deal's package/ folder and nothing else; truth.json is unreachable."""

import os
from pathlib import Path

import pytest

from pipeline.loader import PackageAccessError, PackageLoader

PIPELINE_DIR = Path(__file__).resolve().parents[2] / "pipeline"


@pytest.fixture
def deals(tmp_path):
    pkg = tmp_path / "d99-test" / "package"
    pkg.mkdir(parents=True)
    (pkg / "om.pdf").write_bytes(b"%PDF-1.4")
    (pkg / "notes.txt").write_text("ignored")
    (tmp_path / "d99-test" / "truth.json").write_text('{"secret": true}')
    return tmp_path


def test_lists_only_supported_package_files(deals):
    loader = PackageLoader("d99-test", deals)
    assert [p.name for p in loader.documents()] == ["om.pdf"]


@pytest.mark.parametrize("name", ["../truth.json", "../../d99-test/truth.json", "/etc/passwd", "sub/../../truth.json"])
def test_refuses_paths_outside_package(deals, name):
    loader = PackageLoader("d99-test", deals)
    with pytest.raises(PackageAccessError):
        loader.resolve(name)


def test_refuses_truth_json_by_absolute_path(deals):
    loader = PackageLoader("d99-test", deals)
    with pytest.raises(PackageAccessError):
        loader.read_bytes(deals / "d99-test" / "truth.json")


def test_refuses_truth_json_even_inside_package(deals):
    (deals / "d99-test" / "package" / "truth.json").write_text("{}")
    loader = PackageLoader("d99-test", deals)
    with pytest.raises(PackageAccessError):
        loader.resolve("truth.json")


def test_symlink_out_of_package_is_refused(deals):
    link = deals / "d99-test" / "package" / "escape.pdf"
    os.symlink(deals / "d99-test" / "truth.json", link)
    loader = PackageLoader("d99-test", deals)
    with pytest.raises(PackageAccessError):
        loader.resolve("escape.pdf")
    with pytest.raises(PackageAccessError):
        loader.documents()


@pytest.mark.parametrize("bad", ["../d99-test", "a/b", ".hidden", ""])
def test_rejects_bad_deal_ids(deals, bad):
    with pytest.raises(PackageAccessError):
        PackageLoader(bad, deals)


def test_no_pipeline_module_opens_files_except_through_the_loader():
    """Static guard: only loader.py names truth.json, and no module reads index.json (it lists the answers)."""
    for path in PIPELINE_DIR.rglob("*.py"):
        text = path.read_text()
        if path.name != "loader.py":
            assert "truth.json" not in text, f"{path.name} mentions truth.json"
        assert '"index.json"' not in text and "'index.json'" not in text, f"{path.name} opens index.json"
