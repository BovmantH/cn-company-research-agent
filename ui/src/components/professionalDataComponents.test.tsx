import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it, vi } from 'vitest';

import CompanyResolutionPanel from './CompanyResolutionPanel';
import ProfessionalDataOption from './ProfessionalDataOption';
import ProfessionalDataStatus from './ProfessionalDataStatus';


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

  it.each([
    ['running', null, '正在采集工商司法数据'],
    ['completed', null, '工商司法数据采集完成'],
    ['degraded', 'provider_unavailable', '专业数据未完整纳入'],
    ['budget_blocked', 'budget_blocked', '专业数据受预算限制'],
  ] as const)('展示专业分支状态 %s', (status, reason, expected) => {
    const html = renderToStaticMarkup(
      <ProfessionalDataStatus state={{ status, reason }} />,
    );

    expect(html).toContain(expected);
  });

  it('未知降级原因只显示安全通用文案', () => {
    const html = renderToStaticMarkup(
      <ProfessionalDataStatus
        state={{ status: 'degraded', reason: 'Authorization: Bearer secret' }}
      />,
    );

    expect(html).toContain('专业数据未完整纳入');
    expect(html).toContain('基础 Web 报告仍会正常交付');
    expect(html).not.toContain('Authorization');
    expect(html).not.toContain('secret');
  });

  it.each([
    ['ledger_unavailable', '专业数据服务暂时不可用'],
    ['not_configured', '尚未完成专业数据配置'],
    ['deployment_budget_exhausted', '专业数据额度已用完'],
    ['identity_not_found', '未找到可确认的公司主体'],
    ['identity_unconfirmed', '公司主体尚未完成确认'],
    ['resolution_in_progress', '公司主体解析仍在进行'],
    ['idempotency_conflict', '无法安全重放'],
    ['report_size_limit', '受报告大小限制未完整展开'],
  ])('只把稳定原因码 %s 映射为安全文案', (reason, expected) => {
    const html = renderToStaticMarkup(
      <ProfessionalDataStatus state={{ status: 'degraded', reason }} />,
    );

    expect(html).toContain(expected);
    expect(html).not.toContain(reason);
    expect(html).toContain('role="status"');
    expect(html).toContain('aria-live="polite"');
  });

  it('未请求专业数据时不占用页面空间', () => {
    const html = renderToStaticMarkup(
      <ProfessionalDataStatus
        state={{ status: 'not_requested', reason: null }}
      />,
    );

    expect(html).toBe('');
  });
});
