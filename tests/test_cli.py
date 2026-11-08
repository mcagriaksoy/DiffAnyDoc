from __future__ import annotations

import json
from pathlib import Path

from diffanydoc.cli import build_parser, main


def _write(path: Path, text: str) -> Path:
    path.write_text(text, encoding="utf-8")
    return path


def test_formats_command(capsys) -> None:
    assert main(["formats"]) == 0
    out = capsys.readouterr().out
    assert "pdf" in out and "text" in out


def test_info_command(tmp_path: Path, capsys) -> None:
    file = _write(tmp_path / "doc.txt", "bir\niki\nüç\n")
    assert main(["info", str(file)]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["adapter"] == "text"
    assert payload["blocks"] == 3


def test_json_report(tmp_path: Path, capsys) -> None:
    left = _write(tmp_path / "a.txt", "aynı\nToplam 10.000 TL\n")
    right = _write(tmp_path / "b.txt", "aynı\nToplam 12.500 TL\n")
    assert main(["diff", str(left), str(right), "--format", "json", "--full"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["identical"] is False
    assert payload["stats"]["changed"] == 1
    assert payload["rows"][1]["left"]["number"] == 2
    assert payload["rows"][1]["right"]["text"] == "Toplam 12.500 TL"
    inline_kinds = {seg["kind"] for seg in payload["rows"][1]["right_inline"]}
    assert "insert" in inline_kinds and "equal" in inline_kinds


def test_html_report_written(tmp_path: Path) -> None:
    left = _write(tmp_path / "a.txt", "satır bir\nToplam 10.000 TL\n")
    right = _write(tmp_path / "b.txt", "satır bir\nToplam 12.500 TL\n")
    output = tmp_path / "report" / "diff.html"
    assert main(["diff", str(left), str(right), "-o", str(output)]) == 0
    html = output.read_text(encoding="utf-8")
    assert "<del>" in html and "<ins>" in html
    assert "satır" in html


def test_html_report_follows_language(tmp_path: Path) -> None:
    left = _write(tmp_path / "a.txt", "fiyat 10\n")
    right = _write(tmp_path / "b.txt", "fiyat 12\n")
    output = tmp_path / "diff.html"
    assert main(["--lang", "tr", "diff", str(left), str(right), "-o", str(output)]) == 0
    html = output.read_text(encoding="utf-8")
    assert '<html lang="tr">' in html
    assert "Benzerlik" in html
    assert "Similarity" not in html


def test_fail_on_diff_exit_code(tmp_path: Path) -> None:
    left = _write(tmp_path / "a.txt", "bir\n")
    right = _write(tmp_path / "b.txt", "iki\n")
    assert main(["diff", str(left), str(right), "--fail-on-diff"]) == 1
    assert main(["diff", str(left), str(left), "--fail-on-diff"]) == 0


def test_missing_file_reports_error(tmp_path: Path, capsys) -> None:
    left = _write(tmp_path / "a.txt", "bir\n")
    assert main(["diff", str(left), str(tmp_path / "yok.txt")]) == 2
    assert "yok.txt" in capsys.readouterr().err


def test_serve_command_is_wired_up() -> None:
    parser = build_parser()
    args = parser.parse_args(["serve", "--port", "9000"])
    assert args.command == "serve"
    assert args.port == 9000


def test_select_command_is_wired_up(tmp_path: Path, monkeypatch, capsys) -> None:
    file = _write(tmp_path / "a.txt", "bir\n")
    calls: list[tuple[str, Path]] = []

    def fake_send(slot: str, path: Path) -> bool:
        calls.append((slot, path))
        return True

    monkeypatch.setattr("diffanydoc.session.send_selection", fake_send)
    assert main(["select", "left", str(file)]) == 0
    assert calls == [("left", file.resolve())]
    assert capsys.readouterr().out == ""


def test_select_command_rejects_missing_file(tmp_path: Path, capsys) -> None:
    assert main(["select", "right", str(tmp_path / "missing.txt")]) == 2
    assert "missing.txt" in capsys.readouterr().err


def test_integrate_command_installs_and_removes(monkeypatch, capsys) -> None:
    monkeypatch.setattr("diffanydoc.integrate.install", lambda lang: ["/tmp/left", "/tmp/right"])
    monkeypatch.setattr("diffanydoc.integrate.uninstall", lambda lang: ["/tmp/left"])

    assert main(["integrate", "install"]) == 0
    out = capsys.readouterr().out
    assert "installed" in out and "/tmp/left" in out

    assert main(["integrate", "uninstall"]) == 0
    assert "removed" in capsys.readouterr().out


def test_cli_diff_with_numeric_tolerance(tmp_path: Path, capsys) -> None:
    f1 = tmp_path / "t1.csv"
    f2 = tmp_path / "t2.csv"
    f1.write_text("Cost\n100.50\n", encoding="utf-8")
    f2.write_text("Cost\n100.5002\n", encoding="utf-8")

    # With tolerance 0.01: files match within tolerance
    code = main(["diff", str(f1), str(f2), "--tolerance", "0.01", "--fail-on-diff"])
    assert code == 0

