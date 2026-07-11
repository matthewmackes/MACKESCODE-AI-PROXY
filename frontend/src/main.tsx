import React from 'react';
import ReactDOM from 'react-dom/client';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import './styles.css';
import App from './App';
import { ShellErrorBoundary } from './components/ShellErrorBoundary';

const queryClient = new QueryClient();

ReactDOM.createRoot(document.getElementById('root') as HTMLElement).render(
  <React.StrictMode>
    <QueryClientProvider client={queryClient}>
      <ShellErrorBoundary>
        <App />
      </ShellErrorBoundary>
    </QueryClientProvider>
  </React.StrictMode>
);
