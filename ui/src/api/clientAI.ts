export type ClientAISelection = {
  vendor: string;
  model: string;
  apiKey: string;
};

export type ClientAIProvider = {
  id: string;
  name: string;
  shortName: string;
  description: string;
  apiConsoleUrl: string | null;
  catalogSource: 'official_api' | 'curated';
  requiresKeyToList: boolean;
  availableForResearch: boolean;
};

export type ClientAIModel = {
  id: string;
  name: string;
};

export type ClientAIModelCatalog = {
  vendor: string;
  source: 'official_api' | 'curated';
  availableForResearch: boolean;
  models: ClientAIModel[];
};

type FetchLike = typeof fetch;

const PROVIDER_KEYS = new Set([
  'id',
  'name',
  'short_name',
  'description',
  'api_console_url',
  'catalog_source',
  'requires_key_to_list',
  'available_for_research',
]);
const CATALOG_KEYS = new Set([
  'vendor',
  'source',
  'available_for_research',
  'models',
]);
const MODEL_KEYS = new Set(['id', 'name']);

const isRecord = (value: unknown): value is Record<string, unknown> =>
  typeof value === 'object' && value !== null && !Array.isArray(value);

const hasExactKeys = (value: Record<string, unknown>, allowed: Set<string>) =>
  Object.keys(value).every((key) => allowed.has(key));

const catalogSource = (value: unknown): value is 'official_api' | 'curated' =>
  value === 'official_api' || value === 'curated';

/** 仅保留不会携带内嵌凭据的 HTTPS 控制台地址。 */
const safeApiConsoleUrl = (value: unknown): string | null => {
  if (typeof value !== 'string' || value.length === 0) return null;
  try {
    const parsed = new URL(value);
    if (parsed.protocol !== 'https:' || parsed.username || parsed.password) return null;
    return value;
  } catch {
    return null;
  }
};

/** 严格解析厂商能力，避免把服务端端点或其他敏感字段带入前端状态。 */
export const parseClientProviders = (value: unknown): ClientAIProvider[] | null => {
  if (
    !isRecord(value)
    || Object.keys(value).length !== 1
    || !Array.isArray(value.providers)
  ) return null;

  const providers: ClientAIProvider[] = [];
  for (const provider of value.providers) {
    if (
      !isRecord(provider)
      || !hasExactKeys(provider, PROVIDER_KEYS)
      || typeof provider.id !== 'string'
      || provider.id.length === 0
      || typeof provider.name !== 'string'
      || provider.name.length === 0
      || typeof provider.short_name !== 'string'
      || provider.short_name.length === 0
      || typeof provider.description !== 'string'
      || provider.description.length === 0
      || !catalogSource(provider.catalog_source)
      || typeof provider.requires_key_to_list !== 'boolean'
      || typeof provider.available_for_research !== 'boolean'
    ) return null;
    providers.push({
      id: provider.id,
      name: provider.name,
      shortName: provider.short_name,
      description: provider.description,
      apiConsoleUrl: safeApiConsoleUrl(provider.api_console_url),
      catalogSource: provider.catalog_source,
      requiresKeyToList: provider.requires_key_to_list,
      availableForResearch: provider.available_for_research,
    });
  }
  return providers;
};

/** 严格解析模型目录；模型能力仍以服务端白名单为准。 */
export const parseClientModelCatalog = (
  value: unknown,
): ClientAIModelCatalog | null => {
  if (
    !isRecord(value)
    || !hasExactKeys(value, CATALOG_KEYS)
    || typeof value.vendor !== 'string'
    || value.vendor.length === 0
    || !catalogSource(value.source)
    || typeof value.available_for_research !== 'boolean'
    || !Array.isArray(value.models)
  ) return null;

  const models: ClientAIModel[] = [];
  for (const model of value.models) {
    if (
      !isRecord(model)
      || !hasExactKeys(model, MODEL_KEYS)
      || typeof model.id !== 'string'
      || model.id.length === 0
      || typeof model.name !== 'string'
      || model.name.length === 0
    ) return null;
    models.push({ id: model.id, name: model.name });
  }
  return {
    vendor: value.vendor,
    source: value.source,
    availableForResearch: value.available_for_research,
    models,
  };
};

const apiEndpoint = (apiUrl: string, path: string) =>
  `${apiUrl.replace(/\/$/, '')}${path}`;

export const loadClientProviders = async (
  apiUrl: string,
  signal?: AbortSignal,
  fetcher: FetchLike = fetch,
): Promise<ClientAIProvider[]> => {
  let response: Response;
  try {
    response = await fetcher(apiEndpoint(apiUrl, '/ai/providers'), {
      method: 'GET',
      mode: 'cors',
      credentials: 'omit',
      cache: 'no-store',
      headers: { Accept: 'application/json' },
      signal,
    });
  } catch {
    throw new Error('模型厂商列表暂时不可用');
  }
  if (!response.ok) throw new Error('模型厂商列表暂时不可用');
  let payload: unknown;
  try {
    payload = await response.json() as unknown;
  } catch {
    throw new Error('模型厂商列表格式不正确');
  }
  const providers = parseClientProviders(payload);
  if (!providers) throw new Error('模型厂商列表格式不正确');
  return providers;
};

export const loadClientModels = async (
  apiUrl: string,
  vendor: string,
  apiKey: string,
  signal?: AbortSignal,
  fetcher: FetchLike = fetch,
): Promise<ClientAIModelCatalog> => {
  let response: Response;
  try {
    response = await fetcher(apiEndpoint(apiUrl, '/ai/models'), {
      method: 'POST',
      mode: 'cors',
      credentials: 'omit',
      cache: 'no-store',
      headers: {
        Accept: 'application/json',
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({
        vendor,
        ...(apiKey ? { api_key: apiKey } : {}),
      }),
      signal,
    });
  } catch {
    throw new Error('模型目录暂时不可用');
  }
  if (!response.ok) {
    if (response.status === 401 || response.status === 403) {
      throw new Error('API Key 无效或无权读取模型目录');
    }
    throw new Error('模型目录暂时不可用');
  }
  let payload: unknown;
  try {
    payload = await response.json() as unknown;
  } catch {
    throw new Error('模型目录格式不正确');
  }
  const catalog = parseClientModelCatalog(payload);
  if (!catalog || catalog.vendor !== vendor) {
    throw new Error('模型目录格式不正确');
  }
  return catalog;
};
