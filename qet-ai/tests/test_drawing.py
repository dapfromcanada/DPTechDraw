"""Tests for the drawing generator, run against the real QET binary.

They use the parts in Derek's company "My Parts" folder and write only to
pytest's temp folder.
"""
from __future__ import annotations

import datetime as dt
from pathlib import Path

import pytest

from qet_mcp import drawing as d
from qet_mcp.cli import QetCli

PARTS = [
    {"id": "X1", "part": "terminal_block"},
    {"id": "X2", "part": "terminal_block"},
    {"id": "PE1", "part": "ground"},
    {"id": "J1", "part": "dsub9_male"},
]
WIRES = [
    {"from": "J1:2", "to": "X1:1", "name": "W1", "colour": "red"},
    {"from": "J1:3", "to": "X2:1", "name": "W2", "colour": "white"},
    {"from": "X2:2", "to": "PE1", "name": "PE", "colour": "green-yellow"},
]


@pytest.fixture(scope="module")
def cli() -> QetCli:
    return QetCli()


@pytest.fixture(scope="module")
def library():
    lib = d.load_library()
    for need in ("terminal_block", "ground", "dsub9_male"):
        if need not in lib:
            pytest.skip(f"My Parts is missing '{need}'")
    return lib


def _make(tmp_path: Path, library, **kw) -> Path:
    tree, _ = d.build_drawing("Test", kw.get("parts", PARTS), kw.get("wires", WIRES),
                              library=library, date=dt.date(2026, 11, 11))
    out = tmp_path / "t.qet"
    d.write_tree(tree, out)
    return out


def test_dsub_pins_are_named_1_to_9(library) -> None:
    pins = sorted(p.name for p in library["dsub9_male"].pins)
    assert pins == [str(n) for n in range(1, 10)]


def test_drawing_loads_every_part_and_wire(cli, library, tmp_path) -> None:
    out = _make(tmp_path, library)
    check = d.verify(cli, out, len(PARTS), len(WIRES))
    assert check["loaded_ok"], check["problems"]


def test_nets_follow_the_wires(cli, library, tmp_path) -> None:
    out = _make(tmp_path, library)
    nets = cli.nets(out)
    assert len(nets) >= len(WIRES)


def test_title_block_uses_qet_defaults(library, tmp_path) -> None:
    s = d.read_qet_settings()
    tb = d.read_title_block(_make(tmp_path, library))
    assert tb["author"] == s["defaultauthor"]
    assert tb["date"] == "20261111"
    assert tb["revision"] == "1.0"


def test_unknown_part_is_rejected(library) -> None:
    with pytest.raises(d.DrawingError, match="Unknown part"):
        d.build_drawing("x", [{"id": "A", "part": "flux_capacitor"}], [], library=library)


def test_bad_pin_is_rejected(library) -> None:
    with pytest.raises(d.DrawingError, match="no pin '12'"):
        d.build_drawing("x", PARTS, [{"from": "J1:12", "to": "X1:1"}], library=library)


def test_unknown_colour_is_rejected(library) -> None:
    with pytest.raises(d.DrawingError, match="Unknown wire colour"):
        d.build_drawing("x", PARTS, [{"from": "J1:2", "to": "X1:1", "colour": "plaid"}],
                        library=library)


@pytest.mark.parametrize("cur,nxt", [("1.2", "1.3"), ("1.9", "1.10"), ("2", "2.1"), ("", "1.0")])
def test_next_revision(cur, nxt) -> None:
    assert d.next_revision(cur) == nxt


def test_stamp_changes_only_date_and_revision(library, tmp_path) -> None:
    out = _make(tmp_path, library)
    before = out.read_bytes()
    d.stamp(out, revision="1.1", date=dt.date(2027, 1, 2))
    after = out.read_bytes()
    tb = d.read_title_block(out)
    assert (tb["revision"], tb["date"]) == ("1.1", "20270102")
    # Only the <diagram ...> line differs.
    diff = [a for a, b in zip(before.splitlines(), after.splitlines()) if a != b]
    assert len(diff) == 1 and diff[0].lstrip().startswith(b"<diagram")


def test_stamped_file_still_loads(cli, library, tmp_path) -> None:
    out = _make(tmp_path, library)
    d.stamp(out, revision="1.1")
    assert d.verify(cli, out, len(PARTS), len(WIRES))["loaded_ok"]


# ---------------------------------------------------------------- numbered copies

def test_next_free_copy_counts_up(tmp_path) -> None:
    base = tmp_path / "null_modem.qet"
    base.write_text("x")
    assert d.next_free_copy(base).name == "null_modem_2.qet"
    (tmp_path / "null_modem_2.qet").write_text("x")
    assert d.next_free_copy(base).name == "null_modem_3.qet"
    assert d.next_free_copy(tmp_path / "null_modem_2.qet").name == "null_modem_3.qet"


def test_overwrite_while_qet_open_saves_a_copy(library, tmp_path, monkeypatch) -> None:
    from qet_mcp import server
    monkeypatch.setattr(type(server.cli()), "is_qet_running", staticmethod(lambda: True))
    original = _make(tmp_path, library)
    before = original.read_bytes()
    res = server.qet_create_drawing(title="Changed", parts=PARTS, wires=WIRES,
                                    output=str(original), overwrite=True)
    assert res["ok"] and res["saved_as_copy"], res
    assert Path(res["file"]).name == "t_2.qet"
    assert original.read_bytes() == before          # the open file was not touched


def test_overwrite_when_qet_closed_replaces_with_backup(library, tmp_path, monkeypatch) -> None:
    from qet_mcp import server
    monkeypatch.setattr(type(server.cli()), "is_qet_running", staticmethod(lambda: False))
    original = _make(tmp_path, library)
    res = server.qet_create_drawing(title="Changed", parts=PARTS, wires=WIRES,
                                    output=str(original), overwrite=True)
    assert res["ok"] and Path(res["file"]) == original, res
    assert res["backup"] and Path(res["backup"]).is_file()
    assert d.read_title_block(original)["title"] == "Changed"
