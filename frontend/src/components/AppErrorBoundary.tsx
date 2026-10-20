import { Component } from "react";
import type { ReactNode } from "react";
export default class AppErrorBoundary extends Component<{children:ReactNode},{failed:boolean}> {
  state={failed:false};
  static getDerivedStateFromError() { return {failed:true}; }
  render() {
    if (this.state.failed) return <main className="operations-page" role="alert">
      <h1>Не удалось открыть раздел</h1><p>Обновите страницу. Если ошибка повторяется, обратитесь к администратору.</p>
      <button onClick={()=>window.location.reload()}>Обновить страницу</button>
    </main>;
    return this.props.children;
  }
}
