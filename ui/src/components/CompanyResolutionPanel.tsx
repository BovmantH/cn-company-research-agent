import { Building2, ChevronRight, SearchX, ShieldAlert, X } from 'lucide-react';

import type {
  CompanyCandidateView,
  ProfessionalFlowState,
} from '../research/useProfessionalResearchFlow';
import { glassStyle } from '../styles';


interface CompanyResolutionPanelProps {
  flow: Extract<ProfessionalFlowState, { status: 'candidates' | 'fallback' }>;
  onSelect: (viewId: string) => void;
  onContinueBasic: () => void;
  onCancel: () => void;
}

const Candidate = ({
  candidate,
  onSelect,
}: {
  candidate: CompanyCandidateView;
  onSelect: (viewId: string) => void;
}) => (
  <button
    type="button"
    onClick={() => onSelect(candidate.view_id)}
    className="group flex w-full items-center justify-between gap-4 rounded-xl border border-gray-200/80 bg-white/90 p-4 text-left transition-all hover:-translate-y-0.5 hover:border-[#468BFF]/35 hover:shadow-md focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[#468BFF]"
  >
    <div className="flex min-w-0 items-start gap-3">
      <span className="rounded-lg bg-[#468BFF]/10 p-2 text-[#468BFF]">
        <Building2 className="h-5 w-5" strokeWidth={1.7} />
      </span>
      <span className="min-w-0">
        <span className="block truncate font-medium text-gray-900">
          {candidate.company_name}
        </span>
        <span className="mt-1 block font-mono text-xs tracking-wide text-gray-500">
          {candidate.credit_code}
        </span>
        <span className="mt-1.5 flex flex-wrap gap-x-3 gap-y-1 text-xs text-gray-600">
          {candidate.registration_status && <span>{candidate.registration_status}</span>}
          {candidate.region && <span>{candidate.region}</span>}
        </span>
      </span>
    </div>
    <ChevronRight className="h-5 w-5 shrink-0 text-gray-400 transition-transform group-hover:translate-x-0.5 group-hover:text-[#468BFF]" />
  </button>
);

const CompanyResolutionPanel = ({
  flow,
  onSelect,
  onContinueBasic,
  onCancel,
}: CompanyResolutionPanelProps) => {
  const isCandidates = flow.status === 'candidates';
  const title = isCandidates ? '请选择正确的公司主体' : '专业数据本次未启用';
  const message = flow.status === 'fallback' && flow.reason === 'not_found'
    ? `没有找到与“${flow.query}”匹配的企业主体。`
    : flow.status === 'fallback' && flow.reason === 'blocked'
      ? '当前实例的专业数据额度或服务状态不允许继续查询。'
      : flow.status === 'fallback' && flow.reason === 'in_progress'
        ? '相同主体查询仍在处理中；稍后重新提交会复用本次请求，不会自动新建付费查询。'
      : flow.status === 'fallback' && flow.reason === 'unavailable'
        ? '主体核对暂时失败，未发起后续工商司法查询。'
        : '同名或近似企业不止一家，请根据信用代码、状态和地区确认。';

  return (
    <section className={`${glassStyle.card} relative overflow-hidden border-[#468BFF]/20`} aria-live="polite">
      <div className="absolute left-0 top-0 h-full w-1 bg-[#468BFF]" />
      <div className="flex items-start justify-between gap-4">
        <div className="flex items-start gap-3">
          <span className="rounded-lg bg-amber-50 p-2 text-amber-700">
            {isCandidates
              ? <ShieldAlert className="h-5 w-5" />
              : <SearchX className="h-5 w-5" />}
          </span>
          <div>
            <h2 className="text-lg font-semibold text-gray-900">{title}</h2>
            <p className="mt-1 text-sm leading-6 text-gray-600">{message}</p>
          </div>
        </div>
        <button
          type="button"
          aria-label="取消主体确认"
          onClick={onCancel}
          className="rounded-lg p-2 text-gray-400 transition-colors hover:bg-gray-100 hover:text-gray-700"
        >
          <X className="h-5 w-5" />
        </button>
      </div>

      {isCandidates ? (
        <div className="mt-5 grid gap-3 md:grid-cols-2">
          {flow.candidates.map((candidate) => (
            <Candidate
              key={candidate.view_id}
              candidate={candidate}
              onSelect={onSelect}
            />
          ))}
        </div>
      ) : (
        <div className="mt-5 flex flex-wrap items-center gap-3">
          <button
            type="button"
            onClick={onContinueBasic}
            className="rounded-lg bg-gray-900 px-4 py-2.5 text-sm font-medium text-white transition-colors hover:bg-gray-700"
          >
            继续生成基础报告
          </button>
          <button
            type="button"
            onClick={onCancel}
            className="rounded-lg border border-gray-200 bg-white px-4 py-2.5 text-sm font-medium text-gray-700 transition-colors hover:bg-gray-50"
          >
            返回修改
          </button>
        </div>
      )}
    </section>
  );
};

export default CompanyResolutionPanel;
