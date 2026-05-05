import { Github } from 'lucide-react';

interface HeaderProps {
  glassStyle: string;
}

const Header = ({ glassStyle }: HeaderProps) => {
  const handleImageError = (e: React.SyntheticEvent<HTMLImageElement, Event>) => {
    e.currentTarget.style.display = 'none';
  };

  return (
    <div className="relative mb-16">
      <div className="text-center pt-4">
        <h1 className="text-[48px] font-medium text-[#1a202c] font-['DM_Sans'] tracking-[-1px] leading-[52px] text-center mx-auto antialiased">
          公司调研助手
        </h1>
        <p className="text-gray-600 text-lg font-['DM_Sans'] mt-4">
          面向中文用户的公司深度调研工具
        </p>
      </div>
      <div className="absolute top-0 right-0 flex items-center space-x-2">
        <a
          href="https://tavily.com"
          target="_blank"
          rel="noopener noreferrer"
          className={`text-gray-600 hover:text-gray-900 transition-colors ${glassStyle} rounded-lg flex items-center justify-center`}
          style={{ width: '50px', height: '50px', padding: '2px' }}
          aria-label="Tavily 官网"
        >
          <img
            src="/tavilylogo.png"
            alt="Tavily 标志"
            className="w-full h-full object-contain"
            style={{
              width: '45px',
              height: '45px',
              display: 'block',
              margin: 'auto'
            }}
            onError={handleImageError}
          />
        </a>
        <a
          href="https://github.com/BovmantH/cn-company-research-agent"
          target="_blank"
          rel="noopener noreferrer"
          className={`text-gray-600 hover:text-gray-900 transition-colors ${glassStyle} rounded-lg flex items-center justify-center`}
          style={{ width: '40px', height: '40px', padding: '8px' }}
          aria-label="GitHub 仓库"
        >
          <Github 
            style={{ 
              width: '24px', 
              height: '24px',
              display: 'block',
              margin: 'auto'
            }} 
          />
        </a>
      </div>
    </div>
  );
};

export default Header; 