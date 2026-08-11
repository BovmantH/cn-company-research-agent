import { ExternalLink, FileUp, LockKeyhole } from 'lucide-react';

const OFFICIAL_VERIFICATION_LINKS = [
  { label: '打开爱企查', href: 'https://aiqicha.baidu.com/' },
  { label: '打开执行信息公开网', href: 'https://zxgk.court.gov.cn/' },
] as const;

const OfficialVerificationPanel = () => (
  <section className="rounded-2xl border border-blue-100 bg-blue-50/45 p-4" aria-labelledby="official-verification-title">
    <div className="flex flex-wrap items-center gap-2">
      <h3 id="official-verification-title" className="text-base font-semibold text-slate-900">
        工商司法官方核验
      </h3>
      <span className="rounded-full bg-white px-2 py-0.5 text-xs font-medium text-slate-500 shadow-sm">
        可选
      </span>
    </div>
    <p className="mt-1 text-sm leading-6 text-slate-600">
      可前往官方或公开平台自行核对；大模型检索结果不等同于工商司法核验。
    </p>
    <div className="mt-3 grid gap-2 sm:grid-cols-2">
      {OFFICIAL_VERIFICATION_LINKS.map((link) => (
        <a
          key={link.href}
          href={link.href}
          target="_blank"
          rel="noopener noreferrer"
          className="inline-flex min-h-11 items-center justify-center gap-2 rounded-xl border border-blue-300 bg-white px-3 text-sm font-medium text-blue-700 transition hover:border-blue-500 hover:bg-blue-50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500"
        >
          {link.label}
          <ExternalLink aria-hidden="true" className="h-4 w-4" />
        </a>
      ))}
    </div>
    <button
      type="button"
      disabled
      title="材料上传需要安全的解析与脱敏链路，当前版本暂未开放"
      className="mt-3 inline-flex min-h-12 w-full cursor-not-allowed items-center justify-center gap-2 rounded-xl border border-dashed border-slate-300 bg-white/70 px-3 text-sm font-medium text-slate-400"
    >
      <FileUp aria-hidden="true" className="h-5 w-5" />
      材料上传后续支持
    </button>
    <p className="mt-2 flex items-start gap-2 text-xs leading-5 text-slate-500">
      <LockKeyhole aria-hidden="true" className="mt-0.5 h-3.5 w-3.5 shrink-0" />
      本服务不会读取第三方登录状态、Cookie，也不会绕过验证码或反自动化限制。
    </p>
  </section>
);

export default OfficialVerificationPanel;
