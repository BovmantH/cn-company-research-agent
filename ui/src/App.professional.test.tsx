import { act, create, type ReactTestRenderer } from 'react-test-renderer';
import { afterEach, describe, expect, it, vi } from 'vitest';

import App from './App';
import CompanyResolutionPanel from './components/CompanyResolutionPanel';
import ResearchForm from './components/ResearchForm';
import type { ResearchFormValues } from './research/model';
import type { ClientAISelection } from './api/clientAI';


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
const clientAI: ClientAISelection = {
  vendor: 'qwen',
  model: 'qwen3.7-plus',
  apiKey: 'sk-browser-sentinel',
};


describe('App professional fallback', () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it('主体解析失败后无损转为基础请求并关闭专业开关', async () => {
    const researchBodies: unknown[] = [];
    const requestedUrls: string[] = [];
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      requestedUrls.push(url);
      if (url.endsWith('/ai/providers')) {
        return new Response(JSON.stringify({
          providers: [{
            id: 'qwen',
            name: '通义千问',
            short_name: 'Qwen',
            description: '阿里云百炼提供的通义千问模型服务。',
            catalog_source: 'curated',
            requires_key_to_list: false,
            available_for_research: true,
          }],
        }), { status: 200, headers: { 'Content-Type': 'application/json' } });
      }
      if (url.endsWith('/ai/models')) {
        return new Response(JSON.stringify({
          vendor: 'qwen',
          source: 'curated',
          available_for_research: true,
          models: [{ id: 'qwen3.7-plus', name: 'qwen3.7-plus' }],
        }), { status: 200, headers: { 'Content-Type': 'application/json' } });
      }
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

    const network = renderer.root.findAllByType('svg').find(
      (node) => String(node.props.className).includes('research-network'),
    );
    expect(network).toBeDefined();
    expect(network?.props['aria-hidden']).toBe('true');
    expect(network?.findAllByType('path').slice(0, 3).map((path) => path.props.className))
      .toEqual([
        'research-network-flow research-network-flow-slow',
        'research-network-flow research-network-flow-medium',
        'research-network-flow research-network-flow-fast',
      ]);
    expect(network?.findAllByType('circle').every(
      (node) => String(node.props.className).includes('research-network-node'),
    )).toBe(true);

    await act(async () => {
      await renderer.root.findByType(ResearchForm).props.onSubmit(values, clientAI);
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
      ai: {
        vendor: 'qwen',
        model: 'qwen3.7-plus',
        api_key: 'sk-browser-sentinel',
        web_search: true,
      },
      professional_data: {
        enabled: false,
        fallback_reason: 'provider_unavailable',
      },
    }]);
    expect(JSON.stringify(researchBodies)).not.toContain('resolution_token');
    expect(JSON.stringify(researchBodies)).not.toContain('Authorization');
    expect(JSON.stringify(researchBodies)).not.toContain('upstream-secret');
    expect(requestedUrls).toContain('/capabilities');
    expect(requestedUrls).toContain('/research');
    expect(renderer.root.findByType(ResearchForm).props.professionalDataRequested).toBe(false);
    renderer.unmount();
  });
});
