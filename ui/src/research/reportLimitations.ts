import type { ResearchStreamState } from './researchStreamReducer';

/** 根据稳定原因映射限制说明，不把未知事件的原始 reason 放进页面。 */
export const reportLimitations = (events: ResearchStreamState['degradations']): string[] => {
  const messages = new Set<string>();
  for (const event of events) {
    switch (event.type) {
      case 'research_degraded':
      case 'query_error':
        messages.add('部分检索未完成，相关信息覆盖可能不足，请核对报告来源。');
        break;
      case 'crawl_error':
        messages.add('公司官网正文未能完整提取，请结合其他公开来源核实。');
        break;
      case 'briefing_degraded':
        messages.add('部分分类摘要未生成，相关章节信息可能不足。');
        break;
      case 'report_degraded':
        if (event.reason === 'persistence_failed') {
          messages.add('本次报告可用，但历史保存失败，建议及时下载；重启或过期后可能无法恢复。');
        } else if (event.reason === 'formatting_failed') {
          messages.add('格式整理未完成，已保留原始报告内容。');
        } else {
          messages.add('部分报告处理未完成，请核对来源后使用。');
        }
        break;
    }
  }
  return [...messages];
};
