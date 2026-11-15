from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from diffanydoc.core.ai import (
    AiConfig,
    analyze_comparison,
    build_comparison_digest,
    load_config,
    save_config,
)
from diffanydoc.core.diff.engine import compare
from diffanydoc.web.server import create_app
from tests.pdfgen import write_pdf


def test_ai_config_persistence_and_custom_preset(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("DIFFANYDOC_AI_DIR", str(tmp_path / "ai_store"))
    cfg = AiConfig(
        preset="custom",
        custom_endpoint="http://127.0.0.1:11434/v1",
        custom_model="qwen3.8-flash-next",
    )
    save_config(cfg)
    loaded = load_config()
    assert loaded.preset == "custom"
    assert loaded.custom_model == "qwen3.8-flash-next"
    assert loaded.custom_endpoint == "http://127.0.0.1:11434/v1"


def test_build_comparison_digest_and_analyze_with_mock_llm(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("DIFFANYDOC_AI_DIR", str(tmp_path / "ai_store"))
    save_config(
        AiConfig(
            preset="custom",
            custom_endpoint="http://127.0.0.1:18080/v1",
            custom_model="qwen3.8-flash-next",
        )
    )

    left_pdf = tmp_path / "a.pdf"
    right_pdf = tmp_path / "b.pdf"
    write_pdf(
        left_pdf,
        [
            [
                "Total Amount: 1000 EUR",
                "Clause 4: Confidentiality remains in effect.",
            ]
        ],
    )
    write_pdf(
        right_pdf,
        [
            [
                "Total Amount: 1250 EUR",
                "Clause 4: Confidentiality remains in effect.",
            ]
        ],
        line_offsets={1: (148.0, 60.0)},
    )

    diff_res = compare(left_pdf, right_pdf)
    digest = build_comparison_digest(diff_res)
    assert len(digest) >= 1

    mock_llm_json = json.dumps(
        {
            "summary": "Toplam tutar 1000 EUR'dan 1250 EUR'ya yükselmiş, 4. madde ise yalnızca konum olarak kaymıştır.",
            "verdict": "major_changes",
            "items": [
                {
                    "id": 1,
                    "category": "content",
                    "title": "Toplam Tutar Değişikliği",
                    "explanation": "1000 EUR yerine 1250 EUR yazılmış.",
                },
                {
                    "id": 2,
                    "category": "layout",
                    "title": "Madde 4 Konum Kayması",
                    "explanation": "Metin birebir aynı, yalnızca sağa ve aşağı kaymış.",
                },
            ],
        }
    )

    with patch("diffanydoc.core.ai._chat_completion", return_value=mock_llm_json):
        analysis = analyze_comparison(diff_res, language="tr")

    assert analysis.verdict == "major_changes"
    assert "1250 EUR" in analysis.summary
    assert len(analysis.items) == 2
    assert analysis.items[0].category == "content"
    assert analysis.items[1].category == "layout"


def test_ai_web_endpoints(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DIFFANYDOC_AI_DIR", str(tmp_path / "ai_web"))
    client = TestClient(create_app())

    status_resp = client.get("/api/ai/status")
    assert status_resp.status_code == 200
    status_data = status_resp.json()
    assert "presets" in status_data
    assert any(p["id"] == "qwen-0.5b" for p in status_data["presets"])

    cfg_resp = client.post(
        "/api/ai/config",
        json={
            "preset": "custom",
            "custom_endpoint_url": "http://127.0.0.1:18080/v1",
            "custom_model_name": "qwen3.8-flash-next",
        },
    )
    assert cfg_resp.status_code == 200
    assert cfg_resp.json()["available"] is True

    a = tmp_path / "a.txt"
    b = tmp_path / "b.txt"
    a.write_text("Price: 50 USD\nTerms unchanged.\n", encoding="utf-8")
    b.write_text("Price: 75 USD\nTerms unchanged.\n", encoding="utf-8")

    cmp_resp = client.post("/api/compare-paths", json={"left": str(a), "right": str(b)})
    assert cmp_resp.status_code == 200
    cid = cmp_resp.json()["id"]

    fake_reply = json.dumps(
        {
            "summary": "Price changed from 50 USD to 75 USD.",
            "verdict": "major_changes",
            "items": [
                {
                    "id": 1,
                    "category": "content",
                    "title": "Price increase",
                    "explanation": "Changed from 50 USD to 75 USD.",
                }
            ],
        }
    )
    with patch("diffanydoc.core.ai._chat_completion", return_value=fake_reply):
        ai_resp = client.post(f"/api/compare/{cid}/ai", json={"language": "en"})
    assert ai_resp.status_code == 200
    payload = ai_resp.json()
    assert payload["verdict"] == "major_changes"
    assert payload["items"][0]["title"] == "Price increase"

    # Row-level inline AI explanation endpoint
    row_reply = json.dumps(
        {
            "category": "content",
            "title": "Unit price updated",
            "explanation": "Price increased by 25 USD.",
        }
    )
    with patch("diffanydoc.core.ai._chat_completion", return_value=row_reply):
        row_resp = client.post(
            f"/api/compare/{cid}/ai/row",
            json={"row_index": 0, "language": "en"},
        )
    assert row_resp.status_code == 200
    row_data = row_resp.json()
    assert row_data["category"] == "content"
    assert "25 USD" in row_data["explanation"]

    # HTML and PDF reports include the AI Semantic Analysis section
    html_resp = client.get(f"/api/compare/{cid}/report?lang=en")
    assert html_resp.status_code == 200
    assert "ai-report-box" in html_resp.text
    assert "Price changed from 50 USD to 75 USD." in html_resp.text

    pdf_resp = client.get(f"/api/compare/{cid}/report.pdf?lang=en")
    assert pdf_resp.status_code == 200
    assert pdf_resp.content.startswith(b"%PDF")
