import { Component, type ErrorInfo, type ReactNode } from "react";
import { Button } from "../components/ui";

export class ErrorBoundary extends Component<{ children: ReactNode }, { error: boolean }> {
  state = { error: false };
  static getDerivedStateFromError() { return { error: true }; }
  componentDidCatch(error: Error, info: ErrorInfo) { if (import.meta.env.DEV) console.error(error, info); }
  render() { if (this.state.error) return <main className="grid min-h-dvh place-items-center bg-canvas p-6 text-center text-white"><div><h1 className="text-2xl font-black">Интерфейс временно недоступен</h1><p className="mt-2 text-muted">Данные не потеряны. Обновите страницу и продолжите работу.</p><Button className="mt-5" onClick={() => window.location.reload()}>Обновить страницу</Button></div></main>; return this.props.children; }
}
