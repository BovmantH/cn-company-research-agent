import { act, create, type ReactTestRenderer } from 'react-test-renderer';
import { afterEach, describe, expect, it, vi } from 'vitest';

import App from './App';
import { ResearchForm } from './components';
import type { ResearchFormValues } from './research/model';

vi.mock('./components', () => ({
  Header: () => null,
  ResearchNetworkBackground: () => null,
  ResearchForm: () => <div />,
  ResearchStatus: ({ status, isComplete }: {
    status: { message: string } | null;
    isComplete: boolean;
  }) => <section data-complete={isComplete}>{status?.message}</section>,
  ResearchReport: ({ output }: { output: { details: { report: string } } }) => (
    <article>{output.details.report}</article>
  ),
  ResearchQueries: () => null,
  CurationExtraction: () => null,
  ResearchBriefings: () => null,
  CompanyResolutionPanel: () => null,
  ProfessionalDataStatus: () => null,
}));

class EventSourceStub {
  static readonly CLOSED = 2;
  static instances: EventSourceStub[] = [];
  readyState = 0;
  onopen: (() => void) | null = null;
  onmessage: ((event: MessageEvent) => void) | null = null;
  onerror: (() => void) | null = null;

  constructor() {
    EventSourceStub.instances.push(this);
  }

  emit(payload: { event_id: number; type: string; [key: string]: unknown }) {
    this.onmessage?.(new MessageEvent('message', {
      data: JSON.stringify({ version: 1, ...payload }),
      lastEventId: String(payload.event_id),
    }));
  }

  close() {
    this.readyState = EventSourceStub.CLOSED;
  }
}

const values: ResearchFormValues = {
  companyName: '示例科技',
  companyUrl: '',
  companyHq: '',
  companyIndustry: '',
  professionalDataRequested: false,
};

const renderApp = async (researchResponse: () => Promise<Response>) => {
  vi.stubGlobal('window', { setTimeout, clearTimeout, scrollTo: vi.fn() });
  vi.stubGlobal('EventSource', EventSourceStub);
  vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL) => {
    if (String(input).endsWith('/capabilities')) {
      return new Response(JSON.stringify({
        professional_company_data: {
          enabled: false,
          provider: 'qcc_mcp',
          billing_mode: 'deployment_byok',
          requires_confirmation: true,
          reason: 'not_configured',
        },
      }), { headers: { 'Content-Type': 'application/json' } });
    }
    return researchResponse();
  }));
  let renderer!: ReactTestRenderer;
  await act(async () => {
    renderer = create(<App />);
    await Promise.resolve();
  });
  await act(async () => {
    await renderer.root.findByType(ResearchForm).props.onSubmit(values);
  });
  return renderer;
};

describe('App 调研反馈', () => {
  const renderers: ReactTestRenderer[] = [];

  afterEach(() => {
    for (const renderer of renderers.splice(0)) renderer.unmount();
    EventSourceStub.instances = [];
    vi.unstubAllGlobals();
  });

  it.each([
    [401, 'API Key 无效或无权读取该厂商的官方模型目录'],
    [422, '所选模型在厂商当前官方模型目录中不存在'],
    [503, '该厂商的模型目录暂时不可用，请稍后重试'],
  ])('提交返回%s时展示本站安全中文提示', async (status, detail) => {
    const renderer = await renderApp(async () => new Response(JSON.stringify({ detail }), {
      status,
      headers: { 'Content-Type': 'application/json' },
    }));
    renderers.push(renderer);

    expect(JSON.stringify(renderer.toJSON())).toContain(detail);
    expect(JSON.stringify(renderer.toJSON())).not.toContain('HTTP 请求失败');
  });

  it('网络异常不展示任意异常正文', async () => {
    const renderer = await renderApp(async () => {
      throw new Error('Authorization: Bearer upstream-secret');
    });
    renderers.push(renderer);

    const text = JSON.stringify(renderer.toJSON());
    expect(text).toContain('请检查网络');
    expect(text).not.toContain('Authorization');
    expect(text).not.toContain('upstream-secret');
  });

  it('报告成功时保留去重后的限制说明，不把部分降级改成失败', async () => {
    const renderer = await renderApp(async () => new Response(JSON.stringify({
      status: 'accepted', job_id: 'job-report', message: 'ok',
    }), { headers: { 'Content-Type': 'application/json' } }));
    renderers.push(renderer);
    const stream = EventSourceStub.instances[0];
    await act(async () => {
      stream.emit({ event_id: 1, type: 'research_degraded', reason: 'search_failed' });
      stream.emit({ event_id: 2, type: 'research_degraded', reason: 'search_failed' });
      stream.emit({ event_id: 3, type: 'briefing_degraded', reason: 'empty_response' });
      stream.emit({ event_id: 4, type: 'report_degraded', reason: 'formatting_failed' });
      stream.emit({ event_id: 5, type: 'report_degraded', reason: 'persistence_failed' });
      stream.emit({ event_id: 6, type: 'complete', report: '# 本次报告可用' });
    });

    const text = JSON.stringify(renderer.toJSON());
    expect(text).toContain('报告限制');
    expect(text).toContain('部分检索未完成');
    expect(text).toContain('部分分类摘要未生成');
    expect(text).toContain('格式整理未完成');
    expect(text).toContain('本次报告可用，但历史保存失败');
    expect(text).toContain('建议及时下载');
    expect(text).toContain('重启或过期后可能无法恢复');
    expect(text).toContain('# 本次报告可用');
    expect(text).toContain('调研已完成');
    expect(text).not.toContain('调研失败');
    expect(renderer.root.findAllByType('li')).toHaveLength(4);
    expect(stream.readyState).toBe(EventSourceStub.CLOSED);
  });
});
