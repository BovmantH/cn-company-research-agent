import logging
from typing import Dict

from langchain_core.messages import AIMessage
from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate

from ..classes import ResearchState
from ..classes.state import job_status
from ..prompts import (
    COMPILE_CONTENT_PROMPT,
    CONTENT_SWEEP_PROMPT,
    CONTENT_SWEEP_SYSTEM_MESSAGE,
    EDITOR_SYSTEM_MESSAGE,
)
from ..services.llm_factory import get_llm
from ..utils.references import format_references_section

logger = logging.getLogger(__name__)


class Editor:
    """将各章节简报编排为完整的最终报告。"""

    def __init__(self) -> None:
        # LLM 通过统一工厂获取,默认走 OpenRouter,降级 OpenAI;
        # 模型可通过 LLM_MODEL_EDITOR 环境变量覆盖(默认 anthropic/claude-3.5-sonnet)。
        # editor 阶段需要流式把报告 chunk 推送到前端 SSE,这里显式打开 streaming
        # 以避免 LLM_STREAMING=false 时整篇报告变成一次性返回。
        self.llm = get_llm("editor", streaming=True)

        # 初始化报告上下文
        self.context = {
            "company": "未知公司",
            "industry": "未知行业",
            "hq_location": "未知地点",
        }

    async def compile_briefings(self, state: ResearchState) -> ResearchState:
        """将状态中的各类简报编排为最终报告。"""
        company = state.get("company", "未知公司")
        job_id = state.get("job_id")

        # 使用状态值更新报告上下文
        self.context = {
            "company": company,
            "industry": state.get("industry", "未知行业"),
            "hq_location": state.get("hq_location", "未知地点"),
        }

        msg = [f"📑 正在为 {company} 编排最终报告……"]

        # 发送报告编排开始事件
        if job_id:
            try:
                if job_id in job_status:
                    job_status[job_id]["events"].append(
                        {
                            "type": "report_compilation",
                            "message": f"正在为 {company} 编排最终报告",
                        }
                    )
            except Exception as exc:
                logger.error(
                    "追加 report_compilation 事件失败，异常类型=%s",
                    type(exc).__name__,
                )

        # 从专用状态字段读取各章节简报
        briefing_keys = {
            "company": "company_briefing",
            "industry": "industry_briefing",
            "financial": "financial_briefing",
            "news": "news_briefing",
        }

        individual_briefings = {}
        for category, key in briefing_keys.items():
            if content := state.get(key):
                individual_briefings[category] = content
                msg.append(f"已找到 {category} 简报，共 {len(content)} 个字符")
            else:
                msg.append(f"没有可用的 {category} 简报")
                logger.error("状态中缺少字段：%s", key)

        if not individual_briefings:
            msg.append("\n⚠️ 没有可供编排的简报章节")
            logger.error("状态中没有任何简报")
        else:
            try:
                compiled_report = await self.edit_report(state, individual_briefings)
                if not compiled_report or not compiled_report.strip():
                    logger.error("编排后的报告为空")
                else:
                    logger.info("已成功编排报告，共 %s 个字符", len(compiled_report))
            except Exception as e:
                logger.error(
                    "报告编排失败，异常类型=%s",
                    type(e).__name__,
                )

        state.setdefault("messages", []).append(AIMessage(content="\n".join(msg)))
        return state

    async def edit_report(self, state: ResearchState, briefings: Dict[str, str]) -> str:
        """将章节简报编排为最终报告并更新状态。"""
        try:
            logger.info("开始编排报告")
            job_id = state.get("job_id")

            # 第一步：初步编排
            edited_report = await self.compile_content(state, briefings)
            if not edited_report:
                logger.error("初步编排失败")
                return ""

            # 第二、三步：内容清扫与流式输出
            final_report = ""
            async for event in self.content_sweep(edited_report):
                # 将流式事件转发到 job_status
                if isinstance(event, dict) and job_id:
                    try:
                        if job_id in job_status:
                            job_status[job_id]["events"].append(event)
                            logger.debug(
                                "已追加 report_chunk 事件，共 %s 个字符",
                                len(event.get("chunk", "")),
                            )
                    except Exception as exc:
                        logger.error(
                            "追加 report_chunk 事件失败，异常类型=%s",
                            type(exc).__name__,
                        )

                # 累积报告文本
                if isinstance(event, str):
                    final_report = event

            final_report = final_report or edited_report or ""

            logger.info("最终报告已编排，共 %s 个字符", len(final_report))
            if not final_report.strip():
                logger.error("最终报告为空")
                return ""

            # 将最终报告写入状态
            state["report"] = final_report
            state["status"] = "editor_complete"
            if "editor" not in state or not isinstance(state["editor"], dict):
                state["editor"] = {}
            state["editor"]["report"] = final_report

            return final_report
        except Exception as e:
            logger.error(
                "编辑报告失败，异常类型=%s",
                type(e).__name__,
            )
            return ""

    async def compile_content(
        self, state: ResearchState, briefings: Dict[str, str]
    ) -> str:
        """使用 LCEL 初步编排调研章节。"""
        combined_content = "\n\n".join(content for content in briefings.values())

        references = state.get("references", [])
        reference_text = ""
        if references:
            logger.info("编排时发现 %s 条待加入的参考资料", len(references))
            reference_info = state.get("reference_info", {})
            reference_titles = state.get("reference_titles", {})
            reference_text = format_references_section(
                references, reference_info, reference_titles
            )
            logger.info("编排时已加入 %s 条参考资料", len(references))

        # 创建用于报告编排的 LCEL 链
        compile_prompt = ChatPromptTemplate.from_messages(
            [("system", EDITOR_SYSTEM_MESSAGE), ("user", COMPILE_CONTENT_PROMPT)]
        )

        chain = compile_prompt | self.llm | StrOutputParser()

        try:
            initial_report = await chain.ainvoke(
                {
                    "company": self.context["company"],
                    "industry": self.context["industry"],
                    "hq_location": self.context["hq_location"],
                    "combined_content": combined_content,
                }
            )

            # 追加参考资料章节
            if reference_text:
                initial_report = f"{initial_report}\n\n{reference_text}"

            return initial_report
        except Exception as e:
            logger.error(
                "初步编排失败，异常类型=%s",
                type(e).__name__,
            )
            return combined_content or ""

    async def content_sweep(self, content: str):
        """使用 LCEL 流式清理重复内容并持续产出事件。"""
        # 创建用于内容清扫的 LCEL 链
        sweep_prompt = ChatPromptTemplate.from_messages(
            [("system", CONTENT_SWEEP_SYSTEM_MESSAGE), ("user", CONTENT_SWEEP_PROMPT)]
        )

        chain = sweep_prompt | self.llm | StrOutputParser()

        try:
            accumulated_text = ""
            buffer = ""

            # 使用 LangChain 的 astream 流式处理
            async for chunk in chain.astream(
                {
                    "company": self.context["company"],
                    "industry": self.context["industry"],
                    "hq_location": self.context["hq_location"],
                    "content": content,
                }
            ):
                accumulated_text += chunk
                buffer += chunk

                # 在句子边界产出文本块
                if (
                    any(char in buffer for char in [".", "!", "?", "\n"])
                    and len(buffer) > 10
                ):
                    yield {"type": "report_chunk", "chunk": buffer, "step": "报告编辑"}
                    buffer = ""

            # 产出最后一个缓冲区
            if buffer:
                yield {"type": "report_chunk", "chunk": buffer, "step": "报告编辑"}

            yield accumulated_text.strip()
        except Exception as e:
            logger.error(
                "报告格式化失败，异常类型=%s",
                type(e).__name__,
            )
            yield {
                "type": "report_degraded",
                "reason": "formatting_failed",
                "step": "报告编辑",
            }
            yield content or ""

    async def run(self, state: ResearchState) -> ResearchState:
        state = await self.compile_briefings(state)
        # 确保编辑器输出同时保存在顶层和 editor 字段中
        if "report" in state:
            if "editor" not in state or not isinstance(state["editor"], dict):
                state["editor"] = {}
            state["editor"]["report"] = state["report"]
        return state
