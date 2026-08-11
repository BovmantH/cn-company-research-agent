import { ArrowUpRight, Github, Star } from 'lucide-react';

import { PROJECT_REPOSITORY_URL } from '../constants/project';

const ProjectFooter = () => (
  <footer className="relative z-10 px-4 pb-8 sm:px-6 xl:px-8">
    <div className="mx-auto flex max-w-4xl flex-col items-center justify-between gap-4 rounded-2xl border border-blue-100 bg-white/75 px-5 py-4 text-center shadow-[0_12px_36px_rgba(30,64,175,0.08)] backdrop-blur-xl sm:flex-row sm:text-left">
      <div className="flex items-start gap-3">
        <span className="mt-0.5 inline-flex h-9 w-9 shrink-0 items-center justify-center rounded-xl bg-amber-50 text-amber-600">
          <Star aria-hidden="true" className="h-5 w-5" />
        </span>
        <div>
          <p className="font-semibold text-slate-900">这个项目对你有帮助？</p>
          <p className="mt-1 text-sm leading-6 text-slate-600">
            欢迎在 GitHub 点个 Star，支持我们持续完善开源的企业调研能力。
          </p>
        </div>
      </div>
      <a
        aria-label="前往 GitHub 为项目点 Star"
        href={PROJECT_REPOSITORY_URL}
        target="_blank"
        rel="noopener noreferrer"
        className="inline-flex min-h-11 shrink-0 items-center gap-2 rounded-xl border border-blue-200 bg-blue-50 px-4 text-sm font-semibold text-blue-700 transition hover:border-blue-400 hover:bg-blue-100 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500"
      >
        <Github aria-hidden="true" className="h-4 w-4" />
        去 GitHub 点 Star
        <ArrowUpRight aria-hidden="true" className="h-4 w-4" />
      </a>
    </div>
  </footer>
);

export default ProjectFooter;
