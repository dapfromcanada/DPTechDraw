"""Integration tests against the locally built DPTechDraw.exe.

These are real subprocess calls, not mocks -- the point is to catch upstream
behaviour changes, so mocking would defeat it. They skip cleanly if the
binary or the sample project is missing.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from qet_mcp.cli import QetCli, QetProjectOpenError
from qet_mcp.config import QetConfig, QetNotFoundError

SAMPLE = Path(__file__).resolve().parents[2] / "examples" / "741.qet"

BOM_COLUMNS = [
    "label", "designation", "manufacturer", "manufacturer_reference",
    "quantity", "location", "function", "title", "folio",
]


@pytest.fixture(scope="session")
def cli() -> QetCli:
    try:
        client = QetCli(QetConfig.from_env())
    except QetNotFoundError as exc:
        pytest.skip(str(exc))
    if not client.probe()["cli_supported"]:
        pytest.skip("binary lacks the unreleased CLI export flags")
    return client


@pytest.fixture(scope="session")
def sample() -> Path:
    if not SAMPLE.is_file():
        pytest.skip(f"sample project missing: {SAMPLE}")
    return SAMPLE


def test_probe_reports_supported(cli: QetCli) -> None:
    result = cli.probe()
    assert result["cli_supported"] is True
    assert Path(result["exe"]).is_file()


def test_info_shape(cli: QetCli, sample: Path) -> None:
    info = cli.info(sample)
    for key in ("project", "diagrams", "elements", "conductors", "pages"):
        assert key in info, f"missing key {key!r} in --info output"
    assert info["elements"] > 0
    assert len(info["pages"]) == info["diagrams"]


def test_bom_columns_are_exact(cli: QetCli, sample: Path) -> None:
    """Guards against upstream reordering or renaming BOM columns."""
    rows = cli.bom(sample)
    assert rows, "expected at least one BOM row"
    assert list(rows[0].keys()) == BOM_COLUMNS


def test_bom_row_count_matches_info(cli: QetCli, sample: Path) -> None:
    assert len(cli.bom(sample)) == cli.info(sample)["elements"]


def test_nets_parses(cli: QetCli, sample: Path) -> None:
    assert cli.nets(sample) is not None


def test_wires_empty_is_not_an_error(cli: QetCli, sample: Path) -> None:
    """Upstream exits 1 with 'Nothing to export'; we normalise to []."""
    assert isinstance(cli.wires(sample), list)


def test_links_returns_list(cli: QetCli, sample: Path) -> None:
    assert isinstance(cli.links(sample), list)


def test_missing_project_raises(cli: QetCli) -> None:
    with pytest.raises(FileNotFoundError):
        cli.info("Z:/definitely/not/here.qet")


def test_titleblock_rejects_uppercase_custom_key(cli: QetCli, sample: Path, tmp_path: Path) -> None:
    """QET would drop 'Client' silently and still report success."""
    with pytest.raises(ValueError, match="Invalid title-block keys"):
        cli.set_titleblock(sample, tmp_path / "out.qet", {"Client": "ACME"}, force=True)


def test_titleblock_accepts_lowercase_custom_key(cli: QetCli, sample: Path, tmp_path: Path) -> None:
    out = tmp_path / "stamped.qet"
    cli.set_titleblock(sample, out, {"client": "ACME", "revision": "B"}, force=True)
    assert out.is_file()
    assert "ACME" in out.read_text(encoding="utf-8", errors="ignore")


def test_titleblock_rejects_empty_fields(cli: QetCli, sample: Path, tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        cli.set_titleblock(sample, tmp_path / "out.qet", {}, force=True)


def test_write_guard_trips_when_qet_running(cli: QetCli, sample: Path, tmp_path: Path) -> None:
    if not cli.is_qet_running():
        pytest.skip("DPTechDraw is not running; nothing to guard against")
    with pytest.raises(QetProjectOpenError):
        cli.resave(sample, tmp_path / "out.qet")


def test_resave_is_not_idempotent(cli: QetCli, sample: Path, tmp_path: Path) -> None:
    """Documents verified upstream behaviour so a future fix is noticed.

    Two successive resaves of an already-current-format file still differ.
    If this test starts failing, upstream stabilised terminal ids -- good news,
    and the warnings in cli.py and the docs should be revised.
    """
    first = tmp_path / "a.qet"
    second = tmp_path / "b.qet"
    third = tmp_path / "c.qet"
    cli.resave(sample, first, force=True)
    cli.resave(first, second, force=True)
    cli.resave(second, third, force=True)

    b_lines = second.read_text(encoding="utf-8", errors="ignore").splitlines()
    c_lines = third.read_text(encoding="utf-8", errors="ignore").splitlines()
    changed = sum(1 for x, y in zip(b_lines, c_lines) if x != y)
    assert changed > 0, "resave appears idempotent now -- update the docs"


def test_strict_element_check_catches_float_dimensions(cli: QetCli, tmp_path: Path) -> None:
    """QET's own validator passes this; ours must not."""
    elmt = tmp_path / "bad.elmt"
    elmt.write_text(
        '<definition type="element" width="90.0" height="60" '
        'hotspot_x="45" hotspot_y="30" version="0.100.0">'
        "<names><name lang=\"en\">bad</name></names>"
        "<description></description></definition>",
        encoding="utf-8",
    )
    result = cli.check_element_strict(elmt)
    assert result["strict_passed"] is False
    assert any("width" in p for p in result["problems"])
