import io

from backend.utils.utils import generate_pdf_from_md


def test_generated_pdf_uses_chinese_cid_font() -> None:
    output = io.BytesIO()

    generate_pdf_from_md("# 中文调研报告\n\n这是可读的中文正文。", output)

    pdf = output.getvalue()
    assert pdf.startswith(b"%PDF-")
    assert b"STSong-Light" in pdf
