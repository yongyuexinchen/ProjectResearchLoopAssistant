import type { Metadata } from "next";
import Link from "next/link";
import type { ReactNode } from "react";
import "./globals.css";

export const metadata: Metadata = {
  title: "LoopAtlas · 工程调研工作台",
  description: "对陌生工程做只读调研，输出可追溯的架构图、证据与调研报告。",
};

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="zh-CN">
      <body>
        <div className="shell">
          <header className="topbar">
            <div className="topbar__inner">
              <Link className="brand" href="/projects">
                <span className="brand-mark" aria-hidden="true">
                  <svg viewBox="0 0 32 32" fill="none">
                    <defs>
                      <linearGradient id="la-gradient" x1="0" y1="0" x2="1" y2="1">
                        <stop offset="0%" stopColor="#3fb950" />
                        <stop offset="100%" stopColor="#58a6ff" />
                      </linearGradient>
                    </defs>
                    <rect x="1.25" y="1.25" width="29.5" height="29.5" rx="9" stroke="url(#la-gradient)" strokeWidth="1.8" />
                    <path
                      d="M8.5 21.5c0-6.5 4-10.5 10.5-10.5 2.9 0 4.5 1.6 4.5 4.5s-1.6 4.5-4.5 4.5h-6"
                      stroke="url(#la-gradient)"
                      strokeWidth="2.3"
                      strokeLinecap="round"
                    />
                    <circle cx="23" cy="15.25" r="1.9" fill="url(#la-gradient)" />
                  </svg>
                </span>
                <span>
                  <strong>LoopAtlas</strong>
                  <small>工程调研工作台</small>
                </span>
              </Link>
            </div>
          </header>
          <main className="main">{children}</main>
        </div>
      </body>
    </html>
  );
}
