import {
  CheckCircle2,
  CircleDollarSign,
  Loader2,
  AlertTriangle,
} from 'lucide-react';

import type { ProfessionalStreamState } from '../research/researchStreamReducer';
import {
  isProfessionalFallbackReason,
  PROFESSIONAL_FALLBACK_REASON_TEXT,
} from '../research/professionalFallback';
import { glassStyle } from '../styles';


interface ProfessionalDataStatusProps {
  state: ProfessionalStreamState;
}

const safeDegradationText = (reason: string | null): string => {
  if (reason && isProfessionalFallbackReason(reason)) {
    return PROFESSIONAL_FALLBACK_REASON_TEXT[reason];
  }
  switch (reason) {
    case 'ledger_unavailable':
      return '专业数据服务暂时不可用，基础 Web 报告仍会正常交付。';
    case 'not_configured':
    case 'budget_not_configured':
    case 'signing_secret_missing':
      return '当前部署实例尚未完成专业数据配置，基础 Web 报告仍会正常交付。';
    case 'deployment_budget_exhausted':
    case 'budget_blocked':
      return '当前部署实例的专业数据额度已用完，基础 Web 报告仍会正常交付。';
    case 'idempotency_conflict':
      return '本次专业数据请求无法安全重放，基础 Web 报告仍会正常交付。';
    case 'report_size_limit':
      return '专业数据已采集，但受报告大小限制未完整展开；基础 Web 报告仍会正常交付。';
    default:
      return '专业数据暂时不可用，基础 Web 报告仍会正常交付。';
  }
};

const ProfessionalDataStatus = ({ state }: ProfessionalDataStatusProps) => {
  if (state.status === 'not_requested') return null;

  const view = state.status === 'running'
    ? {
        title: '正在采集工商司法数据',
        description: '正在获取已确认主体的工商、股东、变更及司法风险数据，基础报告会并行生成。',
        accent: 'bg-[#468BFF]',
        iconClass: 'border-[#468BFF]/20 bg-[#468BFF]/10 text-[#468BFF]',
        icon: <Loader2 className="h-5 w-5 animate-spin" aria-hidden="true" />,
      }
    : state.status === 'completed'
      ? {
          title: '工商司法数据采集完成',
          description: '已完成结构化事实校验，任务完成时会确定性写入最终报告，不经过大语言模型改写。',
          accent: 'bg-emerald-500',
          iconClass: 'border-emerald-200 bg-emerald-50 text-emerald-700',
          icon: <CheckCircle2 className="h-5 w-5" aria-hidden="true" />,
        }
      : state.status === 'budget_blocked'
        ? {
            title: '专业数据受预算限制',
            description: '本次专业数据分支未继续，基础 Web 报告仍会正常交付。',
            accent: 'bg-amber-500',
            iconClass: 'border-amber-200 bg-amber-50 text-amber-700',
            icon: <CircleDollarSign className="h-5 w-5" aria-hidden="true" />,
          }
        : {
            title: '专业数据未完整纳入',
            description: safeDegradationText(state.reason),
            accent: 'bg-amber-500',
            iconClass: 'border-amber-200 bg-amber-50 text-amber-700',
            icon: <AlertTriangle className="h-5 w-5" aria-hidden="true" />,
          };

  return (
    <section
      role="status"
      aria-live="polite"
      className={`${glassStyle.card} relative overflow-hidden border-[#468BFF]/15 py-5`}
    >
      <div className={`absolute inset-y-0 left-0 w-1 ${view.accent}`} />
      <div className="flex items-start gap-3 pl-1">
        <span className={`rounded-lg border p-2 ${view.iconClass}`}>
          {view.icon}
        </span>
        <div>
          <div className="flex flex-wrap items-center gap-2">
            <h2 className="text-base font-semibold text-gray-900">{view.title}</h2>
            <span className="rounded-full bg-gray-100 px-2 py-0.5 text-[11px] font-medium text-gray-600">
              专业数据分支
            </span>
          </div>
          <p className="mt-1 text-sm leading-6 text-gray-600">{view.description}</p>
        </div>
      </div>
    </section>
  );
};

export default ProfessionalDataStatus;
