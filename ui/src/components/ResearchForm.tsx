import { useEffect, useRef, useState } from 'react';
import {
  Building2,
  Factory,
  FileSearch,
  Globe,
  Globe2,
  Loader2,
  Search,
  ShieldCheck,
  Sparkles,
} from 'lucide-react';

import type { ClientAISelection } from '../api/clientAI';
import type { CapabilityLoadState } from '../api/companyIntelligence';
import type { ResearchFormValues } from '../research/model';
import AIConfigurationPanel, {
  type AIConfigurationPanelHandle,
} from './AIConfigurationPanel';
import { EXAMPLE_COMPANIES } from './exampleCompanies';
import LocationInput from './LocationInput';
import OfficialVerificationPanel from './OfficialVerificationPanel';
import ProfessionalDataOption from './ProfessionalDataOption';

interface ResearchFormProps {
  onSubmit: (
    formData: ResearchFormValues,
    clientAI?: ClientAISelection,
  ) => Promise<void>;
  apiUrl: string;
  isBusy: boolean;
  busyLabel: string;
  capabilityState: CapabilityLoadState;
  professionalDataRequested: boolean;
  onProfessionalDataChange: (requested: boolean) => void;
  loaderColor: string;
}

const INPUT_CLASS = 'min-h-[52px] w-full rounded-xl border border-slate-200 bg-white py-3 pl-11 pr-4 text-base text-slate-900 shadow-[0_1px_2px_rgba(15,23,42,0.02)] outline-none transition placeholder:text-slate-400 hover:border-blue-300 focus:border-blue-500 focus:ring-4 focus:ring-blue-100';

const ResearchForm = ({
  onSubmit,
  apiUrl,
  isBusy,
  busyLabel,
  capabilityState,
  professionalDataRequested,
  onProfessionalDataChange,
  loaderColor,
}: ResearchFormProps) => {
  const [formData, setFormData] = useState<Omit<
    ResearchFormValues,
    'professionalDataRequested'
  >>({
    companyName: '',
    companyUrl: '',
    companyHq: '',
    companyIndustry: '',
  });
  const [aiError, setAIError] = useState<string | null>(null);
  const aiPanelRef = useRef<AIConfigurationPanelHandle>(null);

  useEffect(() => {
    const available = capabilityState.status === 'ready'
      && capabilityState.capability.enabled;
    if (!available && professionalDataRequested) {
      onProfessionalDataChange(false);
    }
  }, [capabilityState, onProfessionalDataChange, professionalDataRequested]);

  const handleSubmit = async (event: React.FormEvent) => {
    event.preventDefault();
    const aiSubmission = aiPanelRef.current?.getSubmission() ?? null;
    if (!aiSubmission) {
      setAIError('请选择已开放联网调研的厂商、模型，并填写 API Key');
      return;
    }
    setAIError(null);
    try {
      await onSubmit(
        { ...formData, professionalDataRequested },
        aiSubmission.mode === 'client' ? aiSubmission.selection : undefined,
      );
    } finally {
      aiPanelRef.current?.clearSecret();
    }
  };

  const fillExampleData = () => {
    const example = EXAMPLE_COMPANIES[0];
    setFormData({
      companyName: example.name,
      companyUrl: example.url,
      companyHq: example.hq,
      companyIndustry: example.industry,
    });
  };

  return (
    <form onSubmit={handleSubmit} className="space-y-5">
      <div className="grid items-start gap-5 lg:grid-cols-[0.96fr_1.04fr]">
        <div className="research-card p-5 sm:p-6">
          <AIConfigurationPanel
            ref={aiPanelRef}
            apiUrl={apiUrl}
            disabled={isBusy}
          />
          {aiError && (
            <p role="alert" className="mt-4 rounded-xl border border-red-100 bg-red-50 px-3 py-2 text-sm text-red-700">
              {aiError}
            </p>
          )}
        </div>

        <div className="research-card p-5 sm:p-6">
          <div className="mb-5 flex flex-wrap items-center justify-between gap-3">
            <h2 className="text-xl font-semibold text-slate-950">调研对象</h2>
            <button
              type="button"
              onClick={fillExampleData}
              disabled={isBusy}
              className="inline-flex min-h-10 items-center gap-2 rounded-xl border border-blue-100 bg-blue-50 px-3 text-sm font-medium text-blue-700 transition hover:border-blue-300 hover:bg-blue-100 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500 disabled:opacity-50"
            >
              <Sparkles aria-hidden="true" className="h-4 w-4" />
              填入示例
            </button>
          </div>

          <fieldset disabled={isBusy} className="space-y-5 disabled:opacity-75">
            <div className="grid gap-5 sm:grid-cols-2">
              <div>
                <label htmlFor="companyName" className="mb-2 block text-sm font-semibold text-slate-800">
                  公司名称 <span className="text-red-500">*</span>
                </label>
                <div className="relative">
                  <Building2 aria-hidden="true" className="absolute left-3.5 top-1/2 h-5 w-5 -translate-y-1/2 text-blue-600" />
                  <input
                    required
                    id="companyName"
                    type="text"
                    value={formData.companyName}
                    onChange={(event) => setFormData((current) => ({
                      ...current,
                      companyName: event.target.value,
                    }))}
                    className={INPUT_CLASS}
                    placeholder="例如：小米科技有限责任公司"
                  />
                </div>
              </div>

              <div>
                <label htmlFor="companyUrl" className="mb-2 block text-sm font-semibold text-slate-800">
                  公司官网
                </label>
                <div className="relative">
                  <Globe aria-hidden="true" className="absolute left-3.5 top-1/2 h-5 w-5 -translate-y-1/2 text-blue-600" />
                  <input
                    id="companyUrl"
                    type="text"
                    value={formData.companyUrl}
                    onChange={(event) => setFormData((current) => ({
                      ...current,
                      companyUrl: event.target.value,
                    }))}
                    className={INPUT_CLASS}
                    placeholder="例如：mi.com"
                  />
                </div>
              </div>

              <div>
                <label htmlFor="companyHq" className="mb-2 block text-sm font-semibold text-slate-800">
                  总部所在地
                </label>
                <LocationInput
                  value={formData.companyHq}
                  onChange={(value) => setFormData((current) => ({
                    ...current,
                    companyHq: value,
                  }))}
                  className={INPUT_CLASS}
                />
              </div>

              <div>
                <label htmlFor="companyIndustry" className="mb-2 block text-sm font-semibold text-slate-800">
                  所属行业
                </label>
                <div className="relative">
                  <Factory aria-hidden="true" className="absolute left-3.5 top-1/2 h-5 w-5 -translate-y-1/2 text-blue-600" />
                  <input
                    id="companyIndustry"
                    type="text"
                    value={formData.companyIndustry}
                    onChange={(event) => setFormData((current) => ({
                      ...current,
                      companyIndustry: event.target.value,
                    }))}
                    className={INPUT_CLASS}
                    placeholder="例如：消费电子、互联网"
                  />
                </div>
              </div>
            </div>

            <OfficialVerificationPanel />

            <details className="group rounded-2xl border border-slate-200 bg-white">
              <summary className="cursor-pointer list-none px-4 py-3 text-sm font-medium text-slate-600 transition hover:text-blue-700 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-blue-500">
                部署者专业数据能力（高级选项）
              </summary>
              <div className="border-t border-slate-100 p-3">
                <ProfessionalDataOption
                  capabilityState={capabilityState}
                  checked={professionalDataRequested}
                  disabled={isBusy}
                  onChange={onProfessionalDataChange}
                />
              </div>
            </details>
          </fieldset>
        </div>
      </div>

      <div className="flex flex-wrap items-center justify-center gap-2.5" aria-label="调研能力">
        <span className="capability-pill">
          <Globe2 aria-hidden="true" className="h-4 w-4 text-blue-600" />
          联网搜索
        </span>
        <span className="capability-pill">
          <FileSearch aria-hidden="true" className="h-4 w-4 text-blue-600" />
          来源引用
        </span>
        <span className="capability-pill">
          <ShieldCheck aria-hidden="true" className="h-4 w-4 text-emerald-600" />
          不持久化用户 Key
        </span>
      </div>

      <div className="mx-auto max-w-3xl">
        <button
          type="submit"
          disabled={isBusy || !formData.companyName}
          className="group relative flex min-h-[58px] w-full items-center justify-center overflow-hidden rounded-xl bg-gradient-to-r from-blue-600 to-blue-500 px-6 text-base font-semibold text-white shadow-[0_14px_30px_rgba(37,99,235,0.24)] transition hover:-translate-y-0.5 hover:from-blue-700 hover:to-blue-600 hover:shadow-[0_18px_36px_rgba(37,99,235,0.28)] focus-visible:outline-none focus-visible:ring-4 focus-visible:ring-blue-200 disabled:cursor-not-allowed disabled:opacity-50 disabled:hover:translate-y-0"
        >
          {isBusy ? (
            <>
              <Loader2
                aria-hidden="true"
                className="mr-2 h-5 w-5 animate-spin"
                style={{ stroke: loaderColor }}
              />
              {busyLabel}
            </>
          ) : (
            <>
              <Search aria-hidden="true" className="mr-2 h-5 w-5" />
              开始深度调研
            </>
          )}
        </button>
        <p className="mt-3 text-center text-sm text-slate-500">预计生成时间 3–8 分钟</p>
      </div>
    </form>
  );
};

export default ResearchForm;
