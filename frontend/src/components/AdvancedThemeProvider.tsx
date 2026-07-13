import { ReactNode } from 'react';
import { ConfigProvider, theme as antdTheme } from 'antd';
import { useThemeMode } from '../theme';

export default function AdvancedThemeProvider({ children }: { children: ReactNode }) {
  const mode = useThemeMode();
  return (
    <ConfigProvider
      theme={{
        algorithm: mode === 'dark' ? antdTheme.darkAlgorithm : antdTheme.defaultAlgorithm,
        token: {
          colorPrimary: '#0f62fe',
          borderRadius: 0,
          fontFamily: 'var(--font-sans)',
        },
      }}
    >
      {children}
    </ConfigProvider>
  );
}
