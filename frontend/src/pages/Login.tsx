import React from 'react';

const providers = [
  { key: 'azure', label: '使用 Azure 企业账号登录', labelEn: 'Sign in with Azure (Enterprise SSO)', icon: '🏢' },
  { key: 'github', label: '使用 GitHub 账号登录', labelEn: 'Sign in with GitHub', icon: '⌥' },
];

export const Login: React.FC = () => {
  const handleLogin = (provider: string) => {
    window.location.href = `/api/auth/oauth/${provider}/login`;
  };

  return (
    <div className="min-h-screen flex">
      {/* 左侧品牌区 */}
      <div
        className="hidden lg:flex lg:w-1/2 flex-col items-center justify-center p-12 relative overflow-hidden"
        style={{ background: 'linear-gradient(135deg, #1a2744 0%, #243460 60%, #1a2744 100%)' }}
      >
        {/* 背景装饰圆 */}
        <div className="absolute -top-32 -left-32 w-96 h-96 rounded-full opacity-10" style={{ background: '#FFC000' }} />
        <div className="absolute -bottom-24 -right-24 w-72 h-72 rounded-full opacity-10" style={{ background: '#FFC000' }} />
        <div className="absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 w-[600px] h-[600px] rounded-full opacity-5" style={{ background: '#FFC000' }} />

        <div className="relative z-10 flex flex-col items-center text-center max-w-sm">
          <img src="/logo.png" alt="DDI Logo" className="h-16 w-auto mb-8 brightness-0 invert" />
          <h2 className="text-3xl font-bold text-white mb-4 leading-snug">DDI PPT 助手</h2>
          <p className="text-slate-300 text-base leading-relaxed mb-8">
            AI 驱动的专业 PPT 生成工具<br />
            统一品牌风格，一键智能成稿
          </p>
          <div className="space-y-3 w-full text-left">
            {[
              { icon: '✦', text: '一句话生成完整演讲稿' },
              { icon: '✦', text: '美化现有 PPT，统一 DDI 品牌风格' },
              { icon: '✦', text: '大纲 / 定稿文案灵活生成' },
            ].map((item) => (
              <div key={item.text} className="flex items-start gap-3">
                <span className="text-[#FFC000] text-sm mt-0.5">{item.icon}</span>
                <span className="text-slate-200 text-sm">{item.text}</span>
              </div>
            ))}
          </div>
        </div>
      </div>

      {/* 右侧登录区 */}
      <div className="flex-1 flex flex-col items-center justify-center p-6 bg-slate-50">
        {/* 移动端 Logo */}
        <div className="lg:hidden mb-8 text-center">
          <img src="/logo.png" alt="DDI Logo" className="h-12 w-auto mx-auto mb-3" />
        </div>

        <div className="w-full max-w-sm">
          <div className="mb-8">
            <h1 className="text-2xl font-bold text-slate-900">欢迎回来</h1>
            <p className="mt-1.5 text-sm text-slate-500">请使用企业账号登录 DDI PPT 助手</p>
          </div>

          <div className="space-y-3">
            {providers.map((provider) => (
              <button
                key={provider.key}
                type="button"
                onClick={() => handleLogin(provider.key)}
                className="w-full flex items-center gap-3 rounded-xl border border-slate-200 bg-white px-5 py-3.5 text-sm font-semibold text-slate-800 hover:border-[#FFC000] hover:shadow-md transition-all duration-200 group"
              >
                <span className="text-lg w-6 text-center">{provider.icon}</span>
                <span className="flex-1 text-left">{provider.label}</span>
                <span className="text-slate-400 group-hover:text-[#FFC000] transition-colors">→</span>
              </button>
            ))}
          </div>

          <div className="mt-8 pt-6 border-t border-slate-200">
            <p className="text-center text-xs text-slate-400">
              登录即表示您同意 DDI 智睿咨询的使用条款与隐私政策
            </p>
          </div>
        </div>

        <div className="mt-auto pt-10 text-center">
          <p className="text-xs text-slate-400">© 2025 DDI 智睿咨询. All rights reserved.</p>
        </div>
      </div>
    </div>
  );
};
