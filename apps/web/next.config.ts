import type { NextConfig } from "next";

// 后端地址：优先读环境变量，默认本机 8002。
const API_ORIGIN = (process.env.LOOP_API_ORIGIN ?? process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://127.0.0.1:8002").replace(/\/$/, "");

const nextConfig: NextConfig = {
  distDir: process.env.LOOP_NEXT_DIST_DIR ?? ".next",
  reactStrictMode: true,
  // 浏览器侧统一走同源 /api/*，由 Next 转发到后端。
  // 这样 SSE 订阅不再跨域，绕开 CORS、Origin 丢端口以及代理拦截非 80/443 端口的问题。
  async rewrites() {
    return [{ source: "/api/:path*", destination: `${API_ORIGIN}/:path*` }];
  },
  experimental: {
    // 本机通过反向代理/带端口访问时，Server Actions 的 Origin 可能丢端口，
    // 导致 "Invalid Server Actions request"。这里显式放行本地调试用的 host。
    serverActions: {
      allowedOrigins: ["127.0.0.1", "localhost", "127.0.0.1:3000", "localhost:3000"],
    },
  },
};

export default nextConfig;
