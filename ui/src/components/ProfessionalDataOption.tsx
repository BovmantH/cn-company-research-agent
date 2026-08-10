import { Database, ShieldCheck } from 'lucide-react';

import {
  capabilityReasonText,
  type CapabilityLoadState,
} from '../api/companyIntelligence';


interface ProfessionalDataOptionProps {
  capabilityState: CapabilityLoadState;
  checked: boolean;
  disabled: boolean;
  onChange: (checked: boolean) => void;
}

const unavailableText = (state: CapabilityLoadState): string => {
  if (state.status === 'loading') return '正在确认当前部署实例的专业数据能力……';
  if (state.status === 'unavailable') {
    return '暂时无法确认专业数据能力，已关闭工商司法数据；基础调研仍可继续。';
  }
  return state.capability.enabled
    ? '将查询企查查的工商、股东、变更及司法风险数据，可能消耗本服务部署者的企查查积分。'
    : capabilityReasonText(state.capability.reason);
};

const ProfessionalDataOption = ({
  capabilityState,
  checked,
  disabled,
  onChange,
}: ProfessionalDataOptionProps) => {
  const available = capabilityState.status === 'ready'
    && capabilityState.capability.enabled;
  const switchDisabled = disabled || !available;

  return (
    <div className="relative overflow-hidden rounded-xl border border-[#468BFF]/20 bg-[#468BFF]/[0.045] p-4">
      <div className="absolute inset-y-0 left-0 w-1 bg-[#468BFF]" />
      <div className="flex items-start justify-between gap-5 pl-2">
        <div className="flex min-w-0 gap-3">
          <div className="mt-0.5 rounded-lg border border-[#468BFF]/20 bg-white p-2 text-[#468BFF]">
            <Database className="h-5 w-5" strokeWidth={1.7} />
          </div>
          <div>
            <div className="flex flex-wrap items-center gap-2">
              <h3 className="font-['DM_Sans'] text-sm font-semibold tracking-wide text-gray-900">
                工商司法专业数据
              </h3>
              {available && (
                <span className="inline-flex items-center gap-1 rounded-full bg-emerald-50 px-2 py-0.5 text-[11px] font-medium text-emerald-700">
                  <ShieldCheck className="h-3 w-3" /> 当前实例可用
                </span>
              )}
            </div>
            <p className="mt-1.5 max-w-2xl text-xs leading-5 text-gray-600">
              {unavailableText(capabilityState)}
            </p>
            {available && (
              <p className="mt-1 text-[11px] text-gray-500">
                默认关闭；启用后会先核对公司主体，多主体时由你确认。
              </p>
            )}
          </div>
        </div>

        <label className="relative mt-1 inline-flex shrink-0 cursor-pointer items-center">
          <input
            type="checkbox"
            role="switch"
            aria-label="启用工商司法专业数据"
            checked={checked}
            disabled={switchDisabled}
            onChange={(event) => onChange(event.target.checked)}
            className="peer sr-only"
          />
          <span className="h-6 w-11 rounded-full bg-gray-300 transition-colors peer-checked:bg-[#468BFF] peer-focus-visible:outline peer-focus-visible:outline-2 peer-focus-visible:outline-offset-2 peer-focus-visible:outline-[#468BFF] peer-disabled:cursor-not-allowed peer-disabled:opacity-50 after:absolute after:left-0.5 after:top-0.5 after:h-5 after:w-5 after:rounded-full after:bg-white after:shadow-sm after:transition-transform peer-checked:after:translate-x-5" />
        </label>
      </div>
    </div>
  );
};

export default ProfessionalDataOption;
