from fastapi.testclient import TestClient

from application import app


def test_pdf_download_rejects_windows_parent_path(tmp_path, monkeypatch) -> None:
    (tmp_path / "pdfs").mkdir()
    (tmp_path / "secret.txt").write_text("不应公开", encoding="utf-8")
    monkeypatch.chdir(tmp_path)

    response = TestClient(app).get("/research/pdf/..%5Csecret.txt")

    assert response.status_code == 404
    assert "不应公开" not in response.text


def test_pdf_download_serves_file_from_pdf_directory(tmp_path, monkeypatch) -> None:
    pdf_dir = tmp_path / "pdfs"
    pdf_dir.mkdir()
    expected = b"%PDF-safe-fixture"
    (pdf_dir / "report.pdf").write_bytes(expected)
    monkeypatch.chdir(tmp_path)

    response = TestClient(app).get("/research/pdf/report.pdf")

    assert response.status_code == 200
    assert response.content == expected
    assert response.headers["content-type"] == "application/pdf"
