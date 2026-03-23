import React from 'react';

const providers = [
  { key: 'github', label: 'Continue with GitHub' },
  { key: 'azure', label: 'Continue with Azure China' },
];

export const Login: React.FC = () => {
  const handleLogin = (provider: string) => {
    window.location.href = `/api/auth/oauth/${provider}/login`;
  };

  return (
    <div className="min-h-screen bg-gradient-to-br from-slate-100 via-white to-amber-100 flex items-center justify-center p-6">
      <div className="w-full max-w-md rounded-2xl border border-slate-200 bg-white p-8 shadow-xl">
        <div className="mb-6">
          <h1 className="text-3xl font-bold text-slate-900">Banana Slides</h1>
          <p className="mt-2 text-sm text-slate-600">Sign in to continue.</p>
        </div>
        <div className="space-y-3">
          {providers.map((provider) => (
            <button
              key={provider.key}
              type="button"
              onClick={() => handleLogin(provider.key)}
              className="w-full rounded-lg border border-slate-300 bg-white px-4 py-3 text-left text-sm font-semibold text-slate-800 hover:border-slate-400 hover:bg-slate-50"
            >
              {provider.label}
            </button>
          ))}
        </div>
      </div>
    </div>
  );
};
