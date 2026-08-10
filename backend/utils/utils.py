import logging
import os
import re
from typing import Dict, List

from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.platypus import (
    ListFlowable,
    ListItem,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
)

from .references import extract_link_info

logger = logging.getLogger(__name__)


def clean_text(text: str) -> str:
    """替换转义引号和其他特殊字符，清理文本。"""
    text = re.sub(r'",?\s*"pdf_url":.+$', "", text)
    text = text.replace('\\"', '"')
    text = text.replace("\\n", "\n")
    text = text.replace("<para>", "").replace("</para>", "")
    return text.strip()


def generate_pdf_from_md(markdown_content: str, output_pdf) -> None:
    """使用简化的 ReportLab 流程将 Markdown 内容转换为 PDF。

    Args:
        markdown_content (str): The markdown content to convert to PDF
        output_pdf: Either a file path string or a BytesIO object
    """
    try:
        # output_pdf 为文件路径时确保父目录存在
        if isinstance(output_pdf, str):
            os.makedirs(os.path.dirname(os.path.abspath(output_pdf)), exist_ok=True)

        markdown_content = markdown_content.replace(
            "\r\n", "\n"
        )  # 规范化 Windows 换行符
        markdown_content = markdown_content.replace(
            "\\n", "\n"
        )  # 将字面量 \n 转换为换行符

        # 创建 PDF 文档
        doc = SimpleDocTemplate(
            output_pdf,
            pagesize=letter,
            rightMargin=40,
            leftMargin=40,
            topMargin=40,
            bottomMargin=40,
        )

        # 配置样式
        styles = getSampleStyleSheet()

        # 自定义样式
        title_style = ParagraphStyle(
            "Title",
            parent=styles["Heading1"],
            fontSize=20,
            textColor=colors.black,
            spaceAfter=12,
        )

        heading2_style = ParagraphStyle(
            "Heading2",
            parent=styles["Heading2"],
            fontSize=16,
            textColor=colors.black,
            spaceBefore=12,
            spaceAfter=6,
            fontName="Helvetica-Bold",
        )

        heading3_style = ParagraphStyle(
            "Heading3",
            parent=styles["Heading3"],
            fontSize=12,
            textColor=colors.black,
            spaceBefore=10,
            spaceAfter=4,
        )

        normal_style = ParagraphStyle(
            "Normal",
            parent=styles["Normal"],
            fontSize=10,
            textColor=colors.black,
            spaceBefore=2,
            spaceAfter=2,
        )

        list_item_style = ParagraphStyle(
            "ListItem",
            parent=styles["Normal"],
            fontSize=10,
            textColor=colors.black,
            spaceBefore=2,
            spaceAfter=2,
            leftIndent=10,
            firstLineIndent=0,
            bulletIndent=0,
        )

        # 创建 PDF 内容流
        story = []

        # 将 Markdown 内容转换为 PDF 元素
        lines = markdown_content.split("\n")
        i = 0

        # 记录当前是否正在处理列表
        in_list = False
        list_items = []

        while i < len(lines):
            line = lines[i].strip()

            # 跳过空行
            if not line:
                if in_list and list_items:
                    # 当前存在列表时先写出列表
                    story.append(
                        ListFlowable(
                            [
                                ListItem(Paragraph(item, list_item_style))
                                for item in list_items
                            ],
                            bulletType="bullet",
                            leftIndent=10,
                            bulletFontName="Helvetica",
                            bulletFontSize=10,
                            bulletOffsetY=0,
                            bulletDedent=10,
                            spaceAfter=0,
                        )
                    )
                    list_items = []
                    in_list = False

                story.append(Spacer(1, 6))
                i += 1
                continue

            # 标题
            if line.startswith("# "):
                story.append(Paragraph(line[2:], title_style))
            elif line.startswith("## "):
                story.append(Paragraph(line[3:], heading2_style))
            elif line.startswith("### "):
                story.append(Paragraph(line[4:], heading3_style))

            # 项目符号
            elif line.startswith("* "):
                bullet_text = line[2:].strip()  # 移除开头的 *，保留其余星号

                # 处理项目符号中的链接
                if (
                    bullet_text.startswith("[")
                    and "](" in bullet_text
                    and bullet_text.endswith(")")
                ):
                    link_text, link_url = extract_link_info(bullet_text)
                    # 使用简化链接格式，避免潜在的格式问题
                    bullet_text = f'<link href="{link_url}" color="blue"><u>{link_text or link_url}</u></link>'

                list_items.append(bullet_text)
                in_list = True

            # 普通段落，包含链接
            else:
                # 处理粗体和斜体文本
                line = re.sub(r"\*\*(.*?)\*\*", r"<b>\1</b>", line)  # 粗体
                line = re.sub(r"\*(.*?)\*", r"<i>\1</i>", line)  # 斜体

                # 检查文本中的链接
                if "[" in line and "](" in line:
                    try:
                        # 处理链接
                        parts = []
                        last_idx = 0
                        for match in re.finditer(r"\[(.*?)\]\((.*?)\)", line):
                            # 添加链接前的文本
                            if match.start() > last_idx:
                                parts.append(line[last_idx : match.start()])

                            # 添加链接
                            link_text = match.group(1)
                            link_url = match.group(2)
                            parts.append(
                                f'<link href="{link_url}" color="blue"><u>{link_text}</u></link>'
                            )

                            last_idx = match.end()

                        # 添加剩余文本
                        if last_idx < len(line):
                            parts.append(line[last_idx:])

                        line = "".join(parts)
                    except Exception as exc:
                        # 链接处理失败时使用原始文本
                        logger.error(
                            "处理链接失败，异常类型=%s",
                            type(exc).__name__,
                        )

                # 添加段落
                story.append(Paragraph(line, normal_style))

            i += 1

        # 写出剩余列表
        if in_list and list_items:
            story.append(
                ListFlowable(
                    [ListItem(Paragraph(item, list_item_style)) for item in list_items],
                    bulletType="bullet",
                    leftIndent=10,
                    bulletFontName="Helvetica",
                    bulletFontSize=10,
                    bulletOffsetY=0,
                    bulletDedent=10,
                    spaceAfter=0,
                )
            )

        # 生成 PDF
        doc.build(story)

        logger.info("PDF 已成功生成：%s", output_pdf)

    except Exception as exc:
        logger.error(
            "PDF 渲染失败，异常类型=%s",
            type(exc).__name__,
        )
        raise RuntimeError("PDF 渲染失败") from exc


def convert_markdown_to_pdf_elements(markdown_text: str, custom_styles: Dict) -> List:
    """将 Markdown 字符串转换为 ReportLab Flowable 元素列表。

    该辅助函数独立于 generate_pdf_from_md。
    """
    story = []
    current_list_items = []
    in_list = False

    lines = markdown_text.split("\n")
    i = 0

    def process_markdown_formatting(text):
        # 粗体
        text = re.sub(r"(?<!\*)\*\*(.*?)\*\*(?!\*)", r"<b>\1</b>", text)

        # 清理剩余的双星号粗体标记，同时保留项目符号所需的单星号
        text = text.replace("**", "")
        return text

    while i < len(lines):
        line = lines[i].strip()

        # 空行
        if not line:
            if in_list and current_list_items:
                story.append(
                    ListFlowable(
                        [
                            ListItem(
                                Paragraph(item, custom_styles["ListItem"]),
                                value="bullet",
                                leftIndent=20,
                                bulletColor=colors.HexColor("#2c3e50"),
                                bulletType="bullet",
                                bulletFontName="Helvetica",
                                bulletFontSize=10,
                            )
                            for item in current_list_items
                        ],
                        bulletType="bullet",
                        leftIndent=20,
                        bulletOffsetX=10,
                        bulletOffsetY=2,
                        start=None,
                        bulletDedent=20,
                        bulletFormat="•",
                        spaceBefore=4,
                        spaceAfter=4,
                    )
                )
                current_list_items = []
                in_list = False
            story.append(Spacer(1, 6))
            i += 1
            continue

        # 标题
        if line.startswith("#"):
            if in_list and current_list_items:
                # 写出列表
                story.append(
                    ListFlowable(
                        [
                            ListItem(
                                Paragraph(item, custom_styles["ListItem"]),
                                value="bullet",
                                leftIndent=20,
                                bulletColor=colors.HexColor("#2c3e50"),
                                bulletType="bullet",
                                bulletFontName="Helvetica",
                                bulletFontSize=10,
                            )
                            for item in current_list_items
                        ],
                        bulletType="bullet",
                        leftIndent=20,
                        bulletOffsetX=10,
                        bulletOffsetY=2,
                        start=None,
                        bulletDedent=20,
                        bulletFormat="•",
                        spaceBefore=4,
                        spaceAfter=4,
                    )
                )
                current_list_items = []
                in_list = False

            heading_level = len(line.split()[0])  # # 字符的数量
            heading_text = " ".join(line.split()[1:])
            style_name = f"Heading{heading_level}"
            # 使用已有样式或自定义样式
            story.append(
                Paragraph(
                    heading_text,
                    custom_styles.get(style_name, custom_styles["BodyText"]),
                )
            )
            i += 1
            continue

        # 项目符号
        if line.startswith("* "):
            bullet_text = line[2:].strip()  # 移除开头的 *，保留其余星号

            # 处理非参考资料的项目符号
            if (
                bullet_text.startswith("[")
                and "](" in bullet_text
                and bullet_text.endswith(")")
            ):
                # 当前项目符号是链接
                title, url = extract_link_info(bullet_text)
                bullet_text = f'<link href="{url}" color="blue" textColor="blue"><u>{title or url}</u></link>'
            else:
                # 仅处理非链接文本
                bullet_text = process_markdown_formatting(bullet_text)

            # 使用明确的项目符号样式立即添加为单个列表项
            story.append(
                ListFlowable(
                    [
                        ListItem(
                            Paragraph(bullet_text, custom_styles["ListItem"]),
                            value="bullet",
                            leftIndent=20,
                            bulletColor=colors.HexColor("#2c3e50"),
                            bulletType="bullet",
                            bulletFontName="Helvetica",
                            bulletFontSize=10,
                            bulletFormat="•",
                        )
                    ],
                    bulletType="bullet",
                    leftIndent=20,
                    bulletOffsetX=10,
                    bulletOffsetY=2,
                    start=None,
                    bulletDedent=20,
                    bulletFormat="•",
                    spaceBefore=4,
                    spaceAfter=4,
                )
            )

        # 当前正在列表中但遇到其他内容时写出列表
        if in_list and current_list_items:
            story.append(
                ListFlowable(
                    [
                        ListItem(
                            Paragraph(item, custom_styles["ListItem"]),
                            value="bullet",
                            leftIndent=20,
                            bulletColor=colors.HexColor("#2c3e50"),
                            bulletType="bullet",
                            bulletFontName="Helvetica",
                            bulletFontSize=10,
                        )
                        for item in current_list_items
                    ],
                    bulletType="bullet",
                    leftIndent=20,
                    bulletOffsetX=10,
                    bulletOffsetY=2,
                    start=None,
                    bulletDedent=20,
                    bulletFormat="•",
                    spaceBefore=4,
                    spaceAfter=4,
                )
            )
            current_list_items = []
            in_list = False

        # 独立链接
        if line.startswith("[") and "](" in line and line.endswith(")"):
            link_title, link_url = extract_link_info(line)
            # 当前内容已是原始 URL，无需再次处理
            link_paragraph = f'<link href="{link_url}" color="blue" textColor="blue"><u>{link_title or link_url}</u></link>'
            story.append(Paragraph(link_paragraph, custom_styles["Link"]))
            i += 1
            continue

        # 普通段落
        line = clean_text(line)
        line = process_markdown_formatting(line)
        story.append(Paragraph(line, custom_styles["BodyText"]))
        i += 1

    # 在末尾写出剩余的项目符号
    if in_list and current_list_items:
        story.append(
            ListFlowable(
                [
                    ListItem(
                        Paragraph(item, custom_styles["ListItem"]),
                        value="bullet",
                        leftIndent=20,
                        bulletColor=colors.HexColor("#2c3e50"),
                        bulletType="bullet",
                        bulletFontName="Helvetica",
                        bulletFontSize=10,
                    )
                    for item in current_list_items
                ],
                bulletType="bullet",
                leftIndent=20,
                bulletOffsetX=10,
                bulletOffsetY=2,
                start=None,
                bulletDedent=20,
                bulletFormat="•",
                spaceBefore=4,
                spaceAfter=4,
            )
        )

    return story


def get_custom_styles():
    """获取基础样式表并加入自定义样式。"""
    styles = getSampleStyleSheet()

    # 更新列表项样式
    styles.add(
        ParagraphStyle(
            name="ListItem",
            parent=styles["BodyText"],
            leftIndent=30,
            firstLineIndent=0,
            spaceBefore=2,
            spaceAfter=2,
            bulletIndent=15,
            bulletFontName="Helvetica-Bold",
            bulletFontSize=12,
            textColor=colors.HexColor("#2c3e50"),
            leading=14,
        )
    )

    # 更新正文样式
    styles["BodyText"].textColor = colors.HexColor("#2c3e50")
    styles["BodyText"].fontSize = 10
    styles["BodyText"].leading = 14

    # 标题样式
    styles["Heading1"].textColor = colors.HexColor("#2c3e50")
    styles["Heading1"].fontSize = 24
    styles["Heading1"].leading = 28

    styles["Heading2"].textColor = colors.HexColor("#2c3e50")
    styles["Heading2"].fontSize = 18
    styles["Heading2"].leading = 22

    styles["Heading3"].textColor = colors.HexColor("#2c3e50")
    styles["Heading3"].fontSize = 14
    styles["Heading3"].leading = 18

    # 链接样式
    styles.add(
        ParagraphStyle(
            name="Link",
            parent=styles["BodyText"],
            textColor=colors.HexColor("#3498db"),
            fontSize=10,
            leading=14,
        )
    )

    return styles
