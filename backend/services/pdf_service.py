import io
import logging
import os
import re

from backend.utils.utils import generate_pdf_from_md

logger = logging.getLogger(__name__)


class PDFService:
    def __init__(self, config):
        self.output_dir = config.get("pdf_output_dir", "pdfs")
        # 输出目录不存在时创建目录
        os.makedirs(self.output_dir, exist_ok=True)

    def _sanitize_company_name(self, company_name):
        """清理公司名称，使其可以安全地用于文件名。"""
        # 将空格替换为下划线并移除特殊字符
        sanitized = re.sub(r"[^\w\s-]", "", company_name).strip().replace(" ", "_")
        return sanitized.lower()

    def _generate_pdf_filename(self, company_name):
        """根据公司名称生成 PDF 文件名。"""
        sanitized_name = self._sanitize_company_name(company_name)
        return f"{sanitized_name}_report.pdf"

    def generate_pdf_stream(self, markdown_content, company_name=None):
        """
        Generate a PDF from markdown content and return it as a stream.

        Args:
            markdown_content (str): The markdown content to convert to PDF
            company_name (str, optional): The company name to use in the filename

        Returns:
            tuple: (success status, PDF stream or error message)
        """
        try:
            # 未提供公司名称时尝试从报告首行提取
            if not company_name:
                first_line = markdown_content.split("\n")[0].strip()
                if first_line.startswith("# "):
                    company_name = first_line[2:].strip()
                else:
                    company_name = "Company Research"

            # 生成输出文件名
            pdf_filename = self._generate_pdf_filename(company_name)

            # 创建 BytesIO 缓冲区保存 PDF
            pdf_buffer = io.BytesIO()

            # 直接将 PDF 写入缓冲区
            generate_pdf_from_md(markdown_content, pdf_buffer)

            # 将缓冲区位置重置到开头
            pdf_buffer.seek(0)

            # 返回成功状态和缓冲区
            return True, (pdf_buffer, pdf_filename)

        except Exception as exc:
            logger.error(
                "PDF 流生成失败，异常类型=%s",
                type(exc).__name__,
            )
            return False, "pdf_generation_failed"
