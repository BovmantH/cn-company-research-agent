import {
  forwardRef,
  useCallback,
  useEffect,
  useImperativeHandle,
  useMemo,
  useRef,
  useState,
} from 'react';
import { Check, Eye, EyeOff, KeyRound, Loader2, RefreshCw, ShieldCheck } from 'lucide-react';

import {
  loadClientModels as loadClientModelsDefault,
  loadClientProviders as loadClientProvidersDefault,
  type ClientAIModel,
  type ClientAIModelCatalog,
  type ClientAIProvider,
  type ClientAISelection,
} from '../api/clientAI';

export type AIConfigurationPanelHandle = {
  getSubmission: () =>
    | { mode: 'server' }
    | { mode: 'client'; selection: ClientAISelection }
    | null;
  clearSecret: () => void;
};

type AIConfigurationPanelProps = {
  apiUrl: string;
  disabled: boolean;
  loadProviders?: typeof loadClientProvidersDefault;
  loadModels?: typeof loadClientModelsDefault;
};

const AIConfigurationPanel = forwardRef<
  AIConfigurationPanelHandle,
  AIConfigurationPanelProps
>(function AIConfigurationPanel({
  apiUrl,
  disabled,
  loadProviders = loadClientProvidersDefault,
  loadModels = loadClientModelsDefault,
}, ref) {
  const [providers, setProviders] = useState<ClientAIProvider[]>([]);
  const [selectedVendor, setSelectedVendor] = useState('');
  const [models, setModels] = useState<ClientAIModel[]>([]);
  const [selectedModel, setSelectedModel] = useState('');
  const [isLoadingProviders, setIsLoadingProviders] = useState(true);
  const [isLoadingModels, setIsLoadingModels] = useState(false);
  const [showSecret, setShowSecret] = useState(false);
  const [configurationMode, setConfigurationMode] = useState<'client' | 'server'>('client');
  const [hasSecret, setHasSecret] = useState(false);
  const [loadedCatalogSource, setLoadedCatalogSource] = useState<
    'official_api' | 'curated' | null
  >(null);
  const [error, setError] = useState<string | null>(null);
  const secretInputRef = useRef<HTMLInputElement>(null);
  const modelRequestRef = useRef<AbortController | null>(null);

  const selectedProvider = useMemo(
    () => providers.find((provider) => provider.id === selectedVendor) ?? null,
    [providers, selectedVendor],
  );

  const clearSecret = useCallback(() => {
    if (secretInputRef.current) secretInputRef.current.value = '';
    setHasSecret(false);
  }, []);

  const clearCatalog = useCallback(() => {
    modelRequestRef.current?.abort();
    modelRequestRef.current = null;
    setModels([]);
    setSelectedModel('');
    setLoadedCatalogSource(null);
    setError(null);
  }, []);

  const requestModels = useCallback(async (
    provider: ClientAIProvider,
    apiKey: string,
  ) => {
    modelRequestRef.current?.abort();
    const controller = new AbortController();
    modelRequestRef.current = controller;
    setIsLoadingModels(true);
    setError(null);
    try {
      const catalog: ClientAIModelCatalog = await loadModels(
        apiUrl,
        provider.id,
        apiKey,
        controller.signal,
      );
      if (controller.signal.aborted) return;
      setModels(catalog.models);
      setSelectedModel(catalog.models[0]?.id ?? '');
      setLoadedCatalogSource(catalog.source);
      if (catalog.models.length === 0) setError('该厂商当前没有可用模型');
    } catch (reason) {
      if (controller.signal.aborted) return;
      setModels([]);
      setSelectedModel('');
      setError(reason instanceof Error ? reason.message : '模型目录暂时不可用');
    } finally {
      if (modelRequestRef.current === controller) {
        modelRequestRef.current = null;
        setIsLoadingModels(false);
      }
    }
  }, [apiUrl, loadModels]);

  useEffect(() => {
    const controller = new AbortController();
    setIsLoadingProviders(true);
    loadProviders(apiUrl, controller.signal)
      .then((loadedProviders) => {
        if (controller.signal.aborted) return;
        setProviders(loadedProviders);
        const firstAvailable = loadedProviders.find(
          (provider) => provider.availableForResearch,
        ) ?? loadedProviders[0];
        setSelectedVendor(firstAvailable?.id ?? '');
        if (loadedProviders.length === 0) setError('当前没有可用的模型厂商');
      })
      .catch((reason: unknown) => {
        if (controller.signal.aborted) return;
        setError(reason instanceof Error ? reason.message : '模型厂商列表暂时不可用');
      })
      .finally(() => {
        if (!controller.signal.aborted) setIsLoadingProviders(false);
      });
    return () => controller.abort();
  }, [apiUrl, loadProviders]);

  useEffect(() => {
    if (!selectedProvider || selectedProvider.requiresKeyToList) return;
    void requestModels(selectedProvider, '');
    return () => modelRequestRef.current?.abort();
  }, [requestModels, selectedProvider]);

  useEffect(() => () => modelRequestRef.current?.abort(), []);

  useImperativeHandle(ref, () => ({
    getSubmission: () => {
      if (configurationMode === 'server') return { mode: 'server' };
      const apiKey = secretInputRef.current?.value.trim() ?? '';
      if (!selectedProvider?.availableForResearch || !selectedModel || !apiKey) {
        return null;
      }
      return {
        mode: 'client',
        selection: {
          vendor: selectedProvider.id,
          model: selectedModel,
          apiKey,
        },
      };
    },
    clearSecret,
  }), [clearSecret, configurationMode, selectedModel, selectedProvider]);

  const selectVendor = (provider: ClientAIProvider) => {
    if (provider.id === selectedVendor) return;
    clearCatalog();
    clearSecret();
    setSelectedVendor(provider.id);
  };

  const loadSelectedCatalog = () => {
    if (!selectedProvider) return;
    const apiKey = secretInputRef.current?.value.trim() ?? '';
    if (selectedProvider.requiresKeyToList && !apiKey) {
      setError('请先填写该厂商的 API Key');
      return;
    }
    void requestModels(selectedProvider, apiKey);
  };

  const changeConfigurationMode = (mode: 'client' | 'server') => {
    if (mode === configurationMode) return;
    clearSecret();
    setError(null);
    setConfigurationMode(mode);
  };

  return (
    <section aria-labelledby="ai-config-title" className="space-y-5">
      <div className="flex flex-wrap items-center gap-2">
        <h2 id="ai-config-title" className="text-xl font-semibold text-slate-900">
          AI 与联网配置
        </h2>
        <span className="rounded-full bg-blue-50 px-2.5 py-1 text-xs font-medium text-blue-700">
          用户自带 Key
        </span>
      </div>

      <div className="grid grid-cols-2 rounded-xl bg-slate-100 p-1" role="radiogroup" aria-label="模型凭证来源">
        <button
          type="button"
          role="radio"
          aria-checked={configurationMode === 'client'}
          onClick={() => changeConfigurationMode('client')}
          className={`min-h-11 rounded-lg px-3 text-sm font-medium transition focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500 ${configurationMode === 'client' ? 'bg-white text-blue-700 shadow-sm' : 'text-slate-600'}`}
        >
          用户自带 Key
        </button>
        <button
          type="button"
          role="radio"
          aria-checked={configurationMode === 'server'}
          onClick={() => changeConfigurationMode('server')}
          className={`min-h-11 rounded-lg px-3 text-sm font-medium transition focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500 ${configurationMode === 'server' ? 'bg-white text-blue-700 shadow-sm' : 'text-slate-600'}`}
        >
          使用部署者配置
        </button>
      </div>

      {configurationMode === 'server' ? (
        <div className="rounded-xl border border-blue-100 bg-blue-50/70 p-4 text-sm leading-6 text-slate-700">
          本次任务使用部署者在服务端配置的模型和检索服务，不需要在网页填写 Key；若部署者未配置，任务会受控失败。
        </div>
      ) : (

      <fieldset disabled={disabled || isLoadingProviders} className="space-y-4">
        <legend className="mb-2 text-sm font-medium text-slate-700">模型厂商</legend>
        <div
          role="radiogroup"
          aria-label="模型厂商"
          className="grid grid-cols-1 gap-2 sm:grid-cols-2 xl:grid-cols-3"
        >
          {providers.map((provider) => {
            const selected = provider.id === selectedVendor;
            return (
              <button
                key={provider.id}
                type="button"
                role="radio"
                aria-checked={selected}
                onClick={() => selectVendor(provider)}
                className={`min-h-12 rounded-xl border px-3 py-2 text-left transition focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500 ${
                  selected
                    ? 'border-blue-500 bg-blue-50 text-blue-800 shadow-sm'
                    : 'border-slate-200 bg-white text-slate-700 hover:border-blue-300'
                }`}
              >
                <span className="flex items-center justify-between gap-2">
                  <span className="truncate text-sm font-medium">{provider.name}</span>
                  {selected && <Check aria-hidden="true" className="h-4 w-4 shrink-0" />}
                </span>
                <span className={`mt-1 block text-xs ${
                  provider.availableForResearch ? 'text-emerald-700' : 'text-amber-700'
                }`}>
                  {provider.availableForResearch ? '可用于联网调研' : '可查看模型目录'}
                </span>
              </button>
            );
          })}
        </div>

        {isLoadingProviders && (
          <p className="flex items-center gap-2 text-sm text-slate-500" role="status">
            <Loader2 aria-hidden="true" className="h-4 w-4 animate-spin" />
            正在读取模型厂商……
          </p>
        )}

        <div>
          <label htmlFor="client-api-key" className="mb-2 block text-sm font-medium text-slate-700">
            API Key
          </label>
          <div className="relative">
            <KeyRound aria-hidden="true" className="absolute left-3.5 top-1/2 h-5 w-5 -translate-y-1/2 text-blue-600" />
            <input
              ref={secretInputRef}
              id="client-api-key"
              type={showSecret ? 'text' : 'password'}
              autoComplete="off"
              minLength={8}
              maxLength={4096}
              disabled={disabled}
              onInput={(event) => setHasSecret(event.currentTarget.value.length > 0)}
              className="min-h-12 w-full rounded-xl border border-slate-200 bg-white py-2 pl-11 pr-12 text-slate-900 outline-none transition focus:border-blue-500 focus:ring-2 focus:ring-blue-100"
              placeholder="请输入所选厂商的 API Key"
              aria-describedby="client-api-key-help"
            />
            <button
              type="button"
              onClick={() => setShowSecret((visible) => !visible)}
              aria-label={showSecret ? '隐藏 API Key' : '显示 API Key'}
              aria-pressed={showSecret}
              className="absolute right-2 top-1/2 inline-flex h-10 w-10 -translate-y-1/2 items-center justify-center rounded-lg text-slate-500 hover:bg-slate-100 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500"
            >
              {showSecret
                ? <EyeOff aria-hidden="true" className="h-5 w-5" />
                : <Eye aria-hidden="true" className="h-5 w-5" />}
            </button>
          </div>
          <p id="client-api-key-help" className="mt-2 flex items-start gap-2 text-xs leading-5 text-emerald-700">
            <ShieldCheck aria-hidden="true" className="mt-0.5 h-4 w-4 shrink-0" />
            Key 仅在本次任务处理期间驻留内存，不持久化、不写应用日志。Key 会先发送给当前部署实例后端，再由后端访问所选厂商官方端点；请只使用可信部署。
          </p>
        </div>

        <div>
          <label htmlFor="client-model" className="mb-2 block text-sm font-medium text-slate-700">
            模型
          </label>
          <div className="flex gap-2">
            <select
              id="client-model"
              value={selectedModel}
              onChange={(event) => setSelectedModel(event.target.value)}
              disabled={disabled || isLoadingModels || models.length === 0}
              className="min-h-12 w-full rounded-xl border border-slate-200 bg-white px-3 text-slate-800 outline-none transition focus:border-blue-500 focus:ring-2 focus:ring-blue-100 disabled:bg-slate-50"
            >
              {models.length === 0 && (
                <option value="">
                  {selectedProvider?.requiresKeyToList
                    ? '填写 Key 后加载模型列表'
                    : '正在加载模型列表'}
                </option>
              )}
              {models.map((model) => (
                <option key={model.id} value={model.id}>{model.name}</option>
              ))}
            </select>
            {selectedProvider?.requiresKeyToList && (
              <button
                type="button"
                aria-label="加载模型列表"
                onClick={loadSelectedCatalog}
                disabled={disabled || isLoadingModels || !hasSecret}
                className="inline-flex min-h-12 shrink-0 items-center gap-2 rounded-xl border border-blue-200 bg-blue-50 px-3 text-sm font-medium text-blue-700 transition hover:bg-blue-100 disabled:cursor-not-allowed disabled:opacity-50"
              >
                {isLoadingModels
                  ? <Loader2 aria-hidden="true" className="h-4 w-4 animate-spin" />
                  : <RefreshCw aria-hidden="true" className="h-4 w-4" />}
                加载模型列表
              </button>
            )}
          </div>
          {selectedProvider && (
            <div className="mt-2 space-y-1 text-xs leading-5 text-slate-500">
              <p>
                目录来源：{(loadedCatalogSource ?? selectedProvider.catalogSource) === 'official_api'
                  ? '厂商官方动态目录'
                  : '项目维护的推荐清单'}
              </p>
              {selectedProvider.requiresKeyToList && (
                <p>填写 Key 后点击“加载模型列表”；读取目录不会调用模型生成。</p>
              )}
            </div>
          )}
        </div>
      </fieldset>
      )}

      <div aria-live="polite">
        {configurationMode === 'client' && selectedProvider && !selectedProvider.availableForResearch && (
          <p className="text-sm text-amber-700">
            可以查看该厂商的官方模型目录，但原生联网搜索尚未接入，暂不能用它生成带来源引用的报告。
          </p>
        )}
        {error && <p role="alert" className="text-sm text-red-600">{error}</p>}
      </div>
    </section>
  );
});

export default AIConfigurationPanel;
