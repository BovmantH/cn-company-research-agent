import { act, create, type ReactTestRenderer } from 'react-test-renderer';
import { afterEach, describe, expect, it, vi } from 'vitest';

import type { ClientAIModelCatalog, ClientAIProvider } from '../api/clientAI';
import AIConfigurationPanel, {
  type AIConfigurationPanelHandle,
} from './AIConfigurationPanel';

const providers: ClientAIProvider[] = [
  {
    id: 'qwen',
    name: '通义千问',
    catalogSource: 'curated',
    requiresKeyToList: false,
    availableForResearch: true,
  },
  {
    id: 'kimi',
    name: 'Kimi',
    catalogSource: 'official_api',
    requiresKeyToList: true,
    availableForResearch: false,
  },
];

const qwenCatalog: ClientAIModelCatalog = {
  vendor: 'qwen',
  source: 'curated',
  availableForResearch: true,
  models: [{ id: 'qwen3.7-plus', name: 'qwen3.7-plus' }],
};

describe('AIConfigurationPanel', () => {
  afterEach(() => vi.restoreAllMocks());

  it('只在私有输入节点读取 Key，并返回服务端允许的厂商模型', async () => {
    const inputNode = { value: '' };
    const loadProviders = vi.fn(async () => providers);
    const loadModels = vi.fn(async () => qwenCatalog);
    const panelRef = { current: null as AIConfigurationPanelHandle | null };
    let renderer!: ReactTestRenderer;

    await act(async () => {
      renderer = create(
        <AIConfigurationPanel
          ref={panelRef}
          apiUrl=""
          disabled={false}
          loadProviders={loadProviders}
          loadModels={loadModels}
        />,
        {
          createNodeMock: (element) => (
            element.type === 'input' && element.props.type === 'password'
              ? inputNode
              : null
          ),
        },
      );
      await Promise.resolve();
      await Promise.resolve();
    });

    inputNode.value = 'sk-browser-sentinel';
    expect(panelRef.current?.getSubmission()).toEqual({
      mode: 'client',
      selection: {
        vendor: 'qwen',
        model: 'qwen3.7-plus',
        apiKey: 'sk-browser-sentinel',
      },
    });
    expect(JSON.stringify(renderer.toJSON())).not.toContain('sk-browser-sentinel');
    expect(loadModels).toHaveBeenCalledWith('', 'qwen', '', expect.any(AbortSignal));

    panelRef.current?.clearSecret();
    expect(inputNode.value).toBe('');
    expect(panelRef.current?.getSubmission()).toBeNull();
    renderer.unmount();
  });

  it('展示全部厂商，但明确标识尚未开放联网调研的厂商', async () => {
    let renderer!: ReactTestRenderer;
    await act(async () => {
      renderer = create(
        <AIConfigurationPanel
          apiUrl=""
          disabled={false}
          loadProviders={async () => providers}
          loadModels={async () => qwenCatalog}
        />,
      );
      await Promise.resolve();
      await Promise.resolve();
    });

    expect(
      renderer.root
        .findByProps({ 'aria-label': '模型厂商' })
        .findAllByProps({ role: 'radio' }),
    ).toHaveLength(2);
    expect(renderer.root.findAllByProps({ children: '待接入联网' })).toHaveLength(1);
    expect(JSON.stringify(renderer.toJSON())).toContain('项目维护的推荐清单');
    renderer.unmount();
  });

  it('允许显式选择部署者配置并提交旧请求模式', async () => {
    const panelRef = { current: null as AIConfigurationPanelHandle | null };
    let renderer!: ReactTestRenderer;
    await act(async () => {
      renderer = create(
        <AIConfigurationPanel
          ref={panelRef}
          apiUrl=""
          disabled={false}
          loadProviders={async () => providers}
          loadModels={async () => qwenCatalog}
        />,
      );
      await Promise.resolve();
      await Promise.resolve();
    });

    await act(async () => {
      renderer.root.findByProps({ children: '使用部署者配置' }).props.onClick();
    });
    expect(panelRef.current?.getSubmission()).toEqual({ mode: 'server' });
    renderer.unmount();
  });
});
