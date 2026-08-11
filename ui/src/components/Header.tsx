import { BookOpen, Star, Waypoints } from 'lucide-react';

import { PROJECT_README_URL, PROJECT_REPOSITORY_URL } from '../constants/project';

const Header = () => (
  <header className="relative z-20">
    <div className="border-b border-slate-200/80 bg-white/90 shadow-[0_1px_12px_rgba(15,39,73,0.06)] backdrop-blur-xl">
      <div className="mx-auto flex min-h-16 max-w-[1440px] items-center justify-between gap-4 px-4 sm:px-6 xl:px-8">
        <a
          href="#main-content"
          className="inline-flex items-center gap-3 rounded-lg text-slate-950 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500"
        >
          <span className="inline-flex h-9 w-9 items-center justify-center rounded-full border-2 border-blue-600 bg-blue-50 text-blue-600">
            <Waypoints aria-hidden="true" className="h-5 w-5" strokeWidth={2} />
          </span>
          <span className="text-lg font-bold tracking-tight sm:text-xl">企业深度调研</span>
        </a>

        <nav aria-label="主要导航" className="flex items-center gap-1 sm:gap-3">
          <a
            href={PROJECT_README_URL}
            target="_blank"
            rel="noopener noreferrer"
            className="inline-flex min-h-11 items-center gap-2 rounded-xl px-3 text-sm font-medium text-slate-700 transition hover:bg-blue-50 hover:text-blue-700 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500 sm:text-base"
          >
            <BookOpen aria-hidden="true" className="h-5 w-5" />
            <span className="hidden sm:inline">使用说明</span>
          </a>
          <a
            aria-label="前往 GitHub 为项目点 Star"
            href={PROJECT_REPOSITORY_URL}
            target="_blank"
            rel="noopener noreferrer"
            className="inline-flex min-h-11 items-center gap-2.5 rounded-xl border border-blue-200 bg-blue-50/80 px-3 text-left text-slate-700 transition hover:border-blue-400 hover:bg-blue-100 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500"
          >
            <span className="inline-flex h-7 w-7 shrink-0 items-center justify-center rounded-lg bg-amber-50 text-amber-600">
              <Star aria-hidden="true" className="h-4 w-4" />
            </span>
            <span className="hidden leading-tight md:block">
              <span className="block text-xs font-semibold text-slate-900">
                这个项目对你有帮助？
              </span>
              <span className="mt-0.5 block text-[11px] font-medium text-blue-700">
                去 GitHub 点个 Star
              </span>
            </span>
          </a>
        </nav>
      </div>
    </div>

    <div className="mx-auto max-w-4xl px-4 pb-8 pt-9 text-center sm:pb-10 sm:pt-11">
      <p className="mx-auto mb-3 w-fit rounded-full border border-blue-100 bg-white/70 px-3 py-1 text-xs font-medium tracking-wide text-blue-700 shadow-sm backdrop-blur sm:text-sm">
        开源 · 用户自带 Key · 面向中国公司
      </p>
      <h1 className="text-balance text-4xl font-bold tracking-[-0.04em] text-slate-950 sm:text-5xl lg:text-[56px] lg:leading-[1.08]">
        企业深度调研
      </h1>
      <p className="mt-3 text-base text-slate-600 sm:text-lg">
        面向中国公司的公开信息调研助手
      </p>
    </div>
  </header>
);

export default Header;
