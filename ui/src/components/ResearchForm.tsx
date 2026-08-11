import { useState, useRef, useEffect } from 'react';
import { Building2, Factory, Globe, Loader2, Search } from 'lucide-react';
import LocationInput from './LocationInput';
import ExamplePopup from './ExamplePopup';
import type { ExampleCompany } from './exampleCompanies';
import ProfessionalDataOption from './ProfessionalDataOption';
import type { CapabilityLoadState } from '../api/companyIntelligence';
import type { ResearchFormValues } from '../research/model';
import AIConfigurationPanel, {
  type AIConfigurationPanelHandle,
} from './AIConfigurationPanel';
import type { ClientAISelection } from '../api/clientAI';

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
  glassStyle: {
    card: string;
    input: string;
  };
  loaderColor: string;
}

const ResearchForm = ({
  onSubmit,
  apiUrl,
  isBusy,
  busyLabel,
  capabilityState,
  professionalDataRequested,
  onProfessionalDataChange,
  glassStyle,
  loaderColor
}: ResearchFormProps) => {
  const [formData, setFormData] = useState<Omit<
    ResearchFormValues,
    'professionalDataRequested'
  >>({
    companyName: "",
    companyUrl: "",
    companyHq: "",
    companyIndustry: "",
  });
  
  // 动画状态
  const [showExampleSuggestion, setShowExampleSuggestion] = useState(true);
  const [isExampleAnimating, setIsExampleAnimating] = useState(false);
  const [aiError, setAIError] = useState<string | null>(null);
  
  // 动画所需的表单节点引用
  const formRef = useRef<HTMLDivElement>(null);
  const exampleRef = useRef<HTMLDivElement>(null);
  const aiPanelRef = useRef<AIConfigurationPanelHandle>(null);
  
  // 填写公司名称后隐藏示例建议
  useEffect(() => {
    if (formData.companyName) {
      setShowExampleSuggestion(false);
    } else if (!isExampleAnimating) {
      setShowExampleSuggestion(true);
    }
  }, [formData.companyName, isExampleAnimating]);

  useEffect(() => {
    const available = capabilityState.status === 'ready'
      && capabilityState.capability.enabled;
    if (!available && professionalDataRequested) {
      onProfessionalDataChange(false);
    }
  }, [
    capabilityState,
    onProfessionalDataChange,
    professionalDataRequested,
  ]);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
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
  
  const fillExampleData = (example: ExampleCompany) => {
    // 开始示例填充动画
    setIsExampleAnimating(true);
    
    // 让示例建议移动到表单内
    if (exampleRef.current && formRef.current) {
      const exampleRect = exampleRef.current.getBoundingClientRect();
      const formRect = formRef.current.getBoundingClientRect();
      
      // 计算动画位移
      const moveX = formRect.left + 20 - exampleRect.left;
      const moveY = formRect.top + 20 - exampleRect.top;
      
      // 应用位移动画
      exampleRef.current.style.transform = `translate(${moveX}px, ${moveY}px) scale(0.6)`;
      exampleRef.current.style.opacity = '0';
    }
    
    // 动画短暂延迟后填入表单
    setTimeout(() => {
      const newFormData = {
        ...formData,
        companyName: example.name,
        companyUrl: example.url,
        companyHq: example.hq,
        companyIndustry: example.industry
      };
      
      // 更新表单数据
      setFormData(newFormData);
      
      setIsExampleAnimating(false);
    }, 500);
  };

  return (
    <div className="relative" ref={formRef}>
      {/* 示例建议 */}
      <ExamplePopup 
        visible={showExampleSuggestion}
        onExampleSelect={fillExampleData}
        glassStyle={glassStyle}
        exampleRef={exampleRef}
      />

      {/* 主表单 */}
      <div className={`${glassStyle.card} backdrop-blur-2xl bg-white/90 border-gray-200/50 shadow-xl`}>
        <form onSubmit={handleSubmit} className="space-y-6">
          <AIConfigurationPanel
            ref={aiPanelRef}
            apiUrl={apiUrl}
            disabled={isBusy}
          />
          {aiError && (
            <p role="alert" className="text-sm text-red-600">{aiError}</p>
          )}
          <fieldset disabled={isBusy} className="space-y-6 disabled:opacity-75">
            <div className="grid grid-cols-1 md:grid-cols-2 gap-8">
            {/* 公司名称 */}
            <div className="relative group">
              <label
                htmlFor="companyName"
                className="block text-base font-medium text-gray-700 mb-2.5 transition-all duration-200 group-hover:text-gray-900 font-['DM_Sans']"
              >
                公司名称 <span className="text-gray-900/70">*</span>
              </label>
              <div className="relative">
                <div className="absolute inset-0 bg-gradient-to-r from-gray-50/0 via-gray-100/50 to-gray-50/0 opacity-0 group-hover:opacity-100 transition-opacity duration-500 rounded-lg"></div>
                <Building2 className="absolute left-4 top-1/2 -translate-y-1/2 h-5 w-5 stroke-[#468BFF] transition-all duration-200 group-hover:stroke-[#8FBCFA] z-10" strokeWidth={1.5} />
                <input
                  required
                  id="companyName"
                  type="text"
                  value={formData.companyName}
                  onChange={(e) =>
                    setFormData((prev) => ({
                      ...prev,
                      companyName: e.target.value,
                    }))
                  }
                  className={`${glassStyle.input} transition-all duration-300 focus:border-[#468BFF]/50 focus:ring-1 focus:ring-[#468BFF]/50 group-hover:border-[#468BFF]/30 bg-white/80 backdrop-blur-sm text-lg py-4 pl-12 font-['DM_Sans']`}
                  placeholder="输入公司名称"
                />
              </div>
            </div>

            {/* 公司网址 */}
            <div className="relative group">
              <label
                htmlFor="companyUrl"
                className="block text-base font-medium text-gray-700 mb-2.5 transition-all duration-200 group-hover:text-gray-900 font-['DM_Sans']"
              >
                公司网址
              </label>
              <div className="relative">
                <div className="absolute inset-0 bg-gradient-to-r from-gray-50/0 via-gray-100/50 to-gray-50/0 opacity-0 group-hover:opacity-100 transition-opacity duration-500 rounded-lg"></div>
                <Globe className="absolute left-4 top-1/2 -translate-y-1/2 h-5 w-5 stroke-[#468BFF] transition-all duration-200 group-hover:stroke-[#8FBCFA] z-10" strokeWidth={1.5} />
                <input
                  id="companyUrl"
                  type="text"
                  value={formData.companyUrl}
                  onChange={(e) =>
                    setFormData((prev) => ({
                      ...prev,
                      companyUrl: e.target.value,
                    }))
                  }
                  className={`${glassStyle.input} transition-all duration-300 focus:border-[#468BFF]/50 focus:ring-1 focus:ring-[#468BFF]/50 group-hover:border-[#468BFF]/30 bg-white/80 backdrop-blur-sm text-lg py-4 pl-12 font-['DM_Sans']`}
                  placeholder="example.com"
                />
              </div>
            </div>

            {/* 公司总部 */}
            <div className="relative group">
              <label
                htmlFor="companyHq"
                className="block text-base font-medium text-gray-700 mb-2.5 transition-all duration-200 group-hover:text-gray-900 font-['DM_Sans']"
              >
                公司总部
              </label>
              <LocationInput
                value={formData.companyHq}
                onChange={(value) =>
                  setFormData((prev) => ({
                    ...prev,
                    companyHq: value,
                  }))
                }
                className={`${glassStyle.input} transition-all duration-300 focus:border-[#468BFF]/50 focus:ring-1 focus:ring-[#468BFF]/50 group-hover:border-[#468BFF]/30 bg-white/80 backdrop-blur-sm text-lg py-4 pl-12 font-['DM_Sans']`}
              />
            </div>

            {/* 所属行业 */}
            <div className="relative group">
              <label
                htmlFor="companyIndustry"
                className="block text-base font-medium text-gray-700 mb-2.5 transition-all duration-200 group-hover:text-gray-900 font-['DM_Sans']"
              >
                所属行业
              </label>
              <div className="relative">
                <div className="absolute inset-0 bg-gradient-to-r from-gray-50/0 via-gray-100/50 to-gray-50/0 opacity-0 group-hover:opacity-100 transition-opacity duration-500 rounded-lg"></div>
                <Factory className="absolute left-4 top-1/2 -translate-y-1/2 h-5 w-5 stroke-[#468BFF] transition-all duration-200 group-hover:stroke-[#8FBCFA] z-10" strokeWidth={1.5} />
                <input
                  id="companyIndustry"
                  type="text"
                  value={formData.companyIndustry}
                  onChange={(e) =>
                    setFormData((prev) => ({
                      ...prev,
                      companyIndustry: e.target.value,
                    }))
                  }
                  className={`${glassStyle.input} transition-all duration-300 focus:border-[#468BFF]/50 focus:ring-1 focus:ring-[#468BFF]/50 group-hover:border-[#468BFF]/30 bg-white/80 backdrop-blur-sm text-lg py-4 pl-12 font-['DM_Sans']`}
                  placeholder="如:互联网、新能源"
                />
              </div>
            </div>
            </div>

            <ProfessionalDataOption
              capabilityState={capabilityState}
              checked={professionalDataRequested}
              disabled={isBusy}
              onChange={onProfessionalDataChange}
            />
          </fieldset>

          <button
            type="submit"
            disabled={isBusy || !formData.companyName}
            className="relative group w-fit mx-auto block overflow-hidden rounded-lg bg-white/80 backdrop-blur-sm border border-gray-200 transition-all duration-500 hover:bg-gray-50 disabled:opacity-50 disabled:cursor-not-allowed px-12 font-['DM_Sans']"
          >
            <div className="absolute inset-0 bg-gradient-to-r from-gray-50/0 via-gray-100/50 to-gray-50/0 translate-x-[-100%] group-hover:translate-x-[100%] transition-transform duration-1000"></div>
            <div className="relative flex items-center justify-center py-3.5">
              {isBusy ? (
                <>
                  <Loader2 className="animate-spin -ml-1 mr-2 h-5 w-5 loader-icon" style={{ stroke: loaderColor }} />
                  <span className="text-base font-medium text-gray-900/90">{busyLabel}</span>
                </>
              ) : (
                <>
                  <Search className="-ml-1 mr-2 h-5 w-5 text-gray-900/90" />
                  <span className="text-base font-medium text-gray-900/90">开始调研</span>
                </>
              )}
            </div>
          </button>
        </form>
      </div>
    </div>
  );
};

export default ResearchForm;
