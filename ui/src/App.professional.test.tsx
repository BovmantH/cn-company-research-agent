import { act, create, type ReactTestRenderer } from 'react-test-renderer';
import { afterEach, describe, expect, it, vi } from 'vitest';

import App from './App';
import CompanyResolutionPanel from './components/CompanyResolutionPanel';
import ResearchForm from './components/ResearchForm';
import type { ResearchFormValues } from './research/model';


vi.mock('./components/LocationInput', () => ({ default: () => null }));

class EventSourceStub {
  static readonly CLOSED = 2;
  readonly url: string;
  readyState = 0;
  onopen: (() => void) | null = null;
  onmessage: ((event: MessageEvent) => void) | null = null;
  onerror: (() => void) | null = null;

  constructor(url: string) {
    this.url = url;
  }

  close() {
    this.readyState = EventSourceStub.CLOSED;
  }
}

const values: ResearchFormValues = {
  companyName: '示例科技',
  companyUrl: 'example.com',
  companyHq: '上海',
  companyIndustry: '软件',
  professionalDataRequested: true,
};


describe('App professional fallback', () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it('主体解析失败后无损转为基础请求并关闭专业开关', async () => {
    const researchBodies: unknown[] = [];
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url.endsWith('/capabilities')) {
        return new Response(JSON.stringify({
          professional_company_data: {
            enabled: true,
            provider: 'qcc_mcp',
            billing_mode: 'deployment_byok',
            requires_confirmation: true,
            reason: null,
          },
        }), { status: 200, headers: { 'Content-Type': 'application/json' } });
      }
      if (url.endsWith('/companies/resolve')) {
        throw new Error('Authorization: Bearer upstream-secret');
      }
      if (url.endsWith('/research')) {
        researchBodies.push(JSON.parse(String(init?.body)) as unknown);
        return new Response(JSON.stringify({
          status: 'accepted',
          job_id: 'job-base',
          message: 'ok',
        }), { status: 200, headers: { 'Content-Type': 'application/json' } });
      }
      throw new Error('收到非预期请求');
    });
    vi.stubGlobal('fetch', fetchMock);
    vi.stubGlobal('EventSource', EventSourceStub);

    let renderer!: ReactTestRenderer;
    await act(async () => {
      renderer = create(<App />);
      await Promise.resolve();
      await Promise.resolve();
    });

    await act(async () => {
      await renderer.root.findByType(ResearchForm).props.onSubmit(values);
    });
    const prompt = renderer.root.findByType(CompanyResolutionPanel);
    expect(prompt.props.flow).toMatchObject({
      status: 'fallback',
      query: '示例科技',
      reason: 'unavailable',
    });

    await act(async () => {
      prompt.props.onContinueBasic();
      await Promise.resolve();
      await Promise.resolve();
    });

    expect(researchBodies).toEqual([{
      company: '示例科技',
      company_url: 'https://example.com',
      industry: '软件',
      hq_location: '上海',
      professional_data: {
        enabled: false,
        fallback_reason: 'provider_unavailable',
      },
    }]);
    expect(JSON.stringify(researchBodies)).not.toContain('resolution_token');
    expect(JSON.stringify(researchBodies)).not.toContain('Authorization');
    expect(JSON.stringify(researchBodies)).not.toContain('upstream-secret');
    expect(renderer.root.findByType(ResearchForm).props.professionalDataRequested).toBe(false);
    renderer.unmount();
  });
});
