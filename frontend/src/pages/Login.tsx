import React, { useState } from 'react';

export const Login: React.FC = () => {
  const [logoClickCount, setLogoClickCount] = useState(0);
  const showGitHub = logoClickCount >= 3;

  const handleLogin = (provider: string) => {
    window.location.href = `/api/auth/oauth/${provider}/login`;
  };

  const handleLogoClick = () => {
    setLogoClickCount((prev) => prev + 1);
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
          <img src="/ddi-logo.png" alt="DDI 智睿咨询" className="h-20 w-auto mb-8" style={{ filter: 'brightness(0) invert(1)' }} />
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
      <div className="flex-1 flex flex-col items-center p-6 bg-slate-50">
        {/* 上方弹性留白，推内容到视觉中偏下 */}
        <div className="flex-[3]" />

        {/* Logo 区 - 可点击触发隐藏功能 */}
        <div className="mb-10 text-center">
          <img
            src="/ddi-logo.png"
            alt="DDI 智睿咨询"
            className="h-14 w-auto mx-auto mb-2 cursor-pointer select-none"
            onClick={handleLogoClick}
            draggable={false}
          />
          <div className="w-12 h-0.5 bg-[#FFC000] mx-auto mt-3 rounded-full" />
        </div>

        <div className="w-full max-w-sm">
          <div className="mb-8 text-center">
            <h1 className="text-2xl font-bold text-slate-900">欢迎回来</h1>
            <p className="mt-1.5 text-sm text-slate-500">请使用企业账号登录 DDI PPT 助手</p>
          </div>

          {/* Azure SSO 主按钮 - 突出显示 */}
          <button
            type="button"
            onClick={() => handleLogin('azure')}
            className="w-full flex items-center gap-3 rounded-xl bg-[#1a2744] px-5 py-4 text-sm font-semibold text-white hover:bg-[#243460] hover:shadow-lg transition-all duration-200 group"
          >
            <svg className="w-5 h-5 flex-shrink-0" viewBox="0 0 23 23" fill="none">
              <path d="M1 1h10v10H1z" fill="#F25022" />
              <path d="M12 1h10v10H12z" fill="#7FBA00" />
              <path d="M1 12h10v10H1z" fill="#00A4EF" />
              <path d="M12 12h10v10H12z" fill="#FFB900" />
            </svg>
            <span className="flex-1 text-left">使用 Azure 企业账号登录</span>
            <span className="text-slate-400 group-hover:text-[#FFC000] transition-colors">→</span>
          </button>

          <p className="mt-3 text-center text-xs text-slate-400">推荐使用企业 Azure AD 账号一键登录</p>

          {/* GitHub SSO - 隐藏按钮，点击Logo 3次后显示 */}
          {showGitHub && (
            <div className="mt-6 pt-6 border-t border-slate-200">
              <button
                type="button"
                onClick={() => handleLogin('github')}
                className="w-full flex items-center gap-3 rounded-xl border border-slate-200 bg-white px-5 py-3.5 text-sm font-semibold text-slate-800 hover:border-slate-400 hover:shadow-md transition-all duration-200 group"
              >
                <svg className="w-5 h-5 flex-shrink-0" viewBox="0 0 24 24" fill="currentColor">
                  <path d="M12 0C5.37 0 0 5.37 0 12c0 5.31 3.435 9.795 8.205 11.385.6.105.825-.255.825-.57 0-.285-.015-1.23-.015-2.235-3.015.555-3.795-.735-4.035-1.41-.135-.345-.72-1.41-1.23-1.695-.42-.225-1.02-.78-.015-.795.945-.015 1.62.87 1.845 1.23 1.08 1.815 2.805 1.305 3.495.99.105-.78.42-1.305.765-1.605-2.67-.3-5.46-1.335-5.46-5.925 0-1.305.465-2.385 1.23-3.225-.12-.3-.54-1.53.12-3.18 0 0 1.005-.315 3.3 1.23.96-.27 1.98-.405 3-.405s2.04.135 3 .405c2.295-1.56 3.3-1.23 3.3-1.23.66 1.65.24 2.88.12 3.18.765.84 1.23 1.905 1.23 3.225 0 4.605-2.805 5.625-5.475 5.925.435.375.81 1.095.81 2.22 0 1.605-.015 2.895-.015 3.3 0 .315.225.69.825.57A12.02 12.02 0 0024 12c0-6.63-5.37-12-12-12z" />
                </svg>
                <span className="flex-1 text-left">使用 GitHub 账号登录</span>
                <span className="text-slate-400 group-hover:text-slate-600 transition-colors">→</span>
              </button>
            </div>
          )}

          <div className="mt-8 pt-6 border-t border-slate-200">
            <p className="text-center text-xs text-slate-400">
              登录即表示您同意 DDI 智睿咨询的使用条款与隐私政策
            </p>
          </div>
        </div>

        {/* 下方弹性留白 */}
        <div className="flex-[5]" />

        <div className="pt-10 text-center">
          <p className="text-xs text-slate-400">© 2026 DDI 智睿咨询. All rights reserved.</p>
        </div>
      </div>
    </div>
  );
};
