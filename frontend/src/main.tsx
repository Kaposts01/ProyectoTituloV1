import { Component, StrictMode, type ReactNode } from 'react'
import { createRoot } from 'react-dom/client'
import './index.css'
import App from './App.tsx'

class RootErrorBoundary extends Component<{ children: ReactNode }, { message: string | null }> {
  state = { message: null };

  static getDerivedStateFromError(error: Error) {
    return { message: error.message || 'Error inesperado al mostrar la aplicación.' };
  }

  render() {
    if (this.state.message) {
      return (
        <main className="app-shell">
          <p className="error-message">No se pudo mostrar la aplicación.</p>
          <p className="muted-copy">{this.state.message}</p>
          <button onClick={() => window.location.reload()}>Recargar aplicación</button>
        </main>
      );
    }
    return this.props.children;
  }
}

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <RootErrorBoundary>
      <App />
    </RootErrorBoundary>
  </StrictMode>,
)
