import { describe, expect, it } from 'vitest';

import { reportLimitations } from './reportLimitations';

describe('报告限制映射', () => {
  it('未知原因只显示固定说明，专业分支交给已有专业状态组件', () => {
    const messages = reportLimitations([
      { eventId: 1, type: 'report_degraded', reason: 'Authorization: upstream-secret' },
      { eventId: 2, type: 'professional_data_degraded', reason: 'provider_unavailable' },
      { eventId: 3, type: 'professional_data_budget_blocked', reason: 'budget_blocked' },
    ]);
    expect(messages).toEqual(['部分报告处理未完成，请核对来源后使用。']);
    expect(messages.join('')).not.toContain('upstream-secret');
  });
});
