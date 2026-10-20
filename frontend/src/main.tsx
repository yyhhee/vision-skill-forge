import React from "react";
import { createRoot } from "react-dom/client";
import { FrontendRoot } from "./FrontendRoot";
import "./styles.css";

class ErrorBoundary extends React.Component<
  React.PropsWithChildren,
  { failed: boolean }
> {
  state = { failed: false };
  static getDerivedStateFromError() {
    return { failed: true };
  }
  render() {
    return this.state.failed ? (
      <main className="fatal-error">
        <h1>页面遇到问题</h1>
        <p>当前草稿没有被覆盖。请刷新后重新打开。</p>
        <button onClick={() => location.reload()}>重新加载</button>
      </main>
    ) : (
      this.props.children
    );
  }
}
createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <ErrorBoundary>
      <FrontendRoot />
    </ErrorBoundary>
  </React.StrictMode>,
);
