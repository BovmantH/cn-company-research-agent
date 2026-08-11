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
    shortName: 'Qwen',
    description: '阿里云百炼提供的通义千问模型服务。',
    catalogSource: 'curated',
    requiresKeyToList: false,
    availableForResearch: true,
  },
  {
    id: 'kimi',
    name: 'Kimi',
    shortName: 'Kimi',
    description: 'Moonshot AI 提供的 Kimi 模型服务。',
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

  it('分别标识可用于联网调研和仅可查看模型目录的厂商', async () => {
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

    const providerButtons = renderer.root
      .findByProps({ 'aria-label': '模型厂商' })
      .findAllByProps({ role: 'radio' });
    expect(providerButtons).toHaveLength(2);
    expect(providerButtons[0].props['aria-describedby'])
      .toBe('provider-description-qwen');
    expect(renderer.root.findByProps({ 'aria-label': '查看Qwen说明' })
      .props['aria-describedby']).toBe('provider-description-qwen');
    expect(renderer.root.findByProps({
      id: 'provider-description-qwen',
      role: 'tooltip',
    }).props.children).toBe('阿里云百炼提供的通义千问模型服务。');
    expect(renderer.root.findAllByProps({ children: '可用于联网调研' })).toHaveLength(1);
    expect(renderer.root.findAllByProps({ children: '可查看模型目录' })).toHaveLength(1);
    expect(JSON.stringify(renderer.toJSON())).toContain('项目维护的推荐清单');
    renderer.unmount();
  });

  it('动态目录要求先填写 Key，再由用户主动加载模型列表', async () => {
    const inputNode = { value: '' };
    const loadModels = vi.fn(async () => qwenCatalog);
    let renderer!: ReactTestRenderer;

    await act(async () => {
      renderer = create(
        <AIConfigurationPanel
          apiUrl=""
          disabled={false}
          loadProviders={async () => providers}
          loadModels={loadModels}
        />,
        {
          createNodeMock: (element) => (
            element.type === 'input' && element.props.id === 'client-api-key'
              ? inputNode
              : null
          ),
        },
      );
      await Promise.resolve();
      await Promise.resolve();
    });

    const providerButtons = renderer.root
      .findByProps({ 'aria-label': '模型厂商' })
      .findAllByProps({ role: 'radio' });
    await act(async () => providerButtons[1].props.onClick());

    expect(renderer.root.findByProps({ id: 'client-model' }).props.children[0].props.children)
      .toBe('填写 Key 后加载模型列表');
    const loadButton = renderer.root.findByProps({ 'aria-label': '加载模型列表' });
    expect(loadButton.props.disabled).toBe(true);
    expect(loadModels).toHaveBeenCalledTimes(1);

    inputNode.value = 'sk-kimi-sentinel';
    await act(async () => {
      renderer.root.findByProps({ id: 'client-api-key' }).props.onInput({
        currentTarget: inputNode,
      });
    });
    expect(loadButton.props.disabled).toBe(false);

    await act(async () => loadButton.props.onClick());
    expect(loadModels).toHaveBeenLastCalledWith(
      '',
      'kimi',
      'sk-kimi-sentinel',
      expect.any(AbortSignal),
    );
    expect(JSON.stringify(renderer.toJSON())).not.toContain('sk-kimi-sentinel');
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
