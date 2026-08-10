import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it, vi } from 'vitest';

import CompanyResolutionPanel from './CompanyResolutionPanel';
import ProfessionalDataOption from './ProfessionalDataOption';


describe('professional data components', () => {
  it('能力不可用时禁用开关但明确基础调研可继续', () => {
    const html = renderToStaticMarkup(
      <ProfessionalDataOption
        capabilityState={{
          status: 'ready',
          capability: {
            enabled: false,
            provider: 'qcc_mcp',
            billing_mode: 'deployment_byok',
            requires_confirmation: true,
            reason: 'deployment_budget_exhausted',
          },
        }}
        checked={false}
        disabled={false}
        onChange={vi.fn()}
      />,
    );

    expect(html).toContain('disabled');
    expect(html).toContain('今日专业数据额度已用完');
    expect(html).toContain('基础调研');
  });

  it('能力可用时说明部署者积分并保持默认关闭', () => {
    const html = renderToStaticMarkup(
      <ProfessionalDataOption
        capabilityState={{
          status: 'ready',
          capability: {
            enabled: true,
            provider: 'qcc_mcp',
            billing_mode: 'deployment_byok',
            requires_confirmation: true,
            reason: null,
          },
        }}
        checked={false}
        disabled={false}
        onChange={vi.fn()}
      />,
    );

    expect(html).not.toContain('checked=""');
    expect(html).toContain('部署者的企查查积分');
  });

  it('候选界面只渲染公开识别字段，不包含 Token', () => {
    const html = renderToStaticMarkup(
      <CompanyResolutionPanel
        flow={{
          status: 'candidates',
          query: '示例科技',
          candidates: [
            {
              view_id: 'view-1',
              company_name: '示例科技有限公司',
              credit_code: '91320594MA1N00000X',
              registration_status: '存续',
              region: '江苏省',
            },
          ],
        }}
        onSelect={vi.fn()}
        onContinueBasic={vi.fn()}
        onCancel={vi.fn()}
      />,
    );

    expect(html).toContain('示例科技有限公司');
    expect(html).toContain('91320594MA1N00000X');
    expect(html).not.toContain('resolution_token');
    expect(html).not.toContain('signed.');
  });
});
