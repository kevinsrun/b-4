import type { NextConfig } from "next";

/**
 * Requests to /api are proxied to the Python API, so the browser talks to one
 * origin and the scientific system stays the only source of truth. Point
 * BACTERION_API_URL at the FastAPI server if it is not on the default port.
 *
 * On Vercel the platform routes /api and /health to the Python function before
 * Next sees them (see vercel.json), so the rewrite must not be installed there:
 * it would otherwise try to proxy to 127.0.0.1:8000 inside the build container,
 * where nothing is listening.
 */
const apiUrl = process.env.BACTERION_API_URL;
const onVercel = Boolean(process.env.VERCEL);

const nextConfig: NextConfig = {
  async rewrites() {
    if (onVercel && !apiUrl) return [];
    const target = apiUrl ?? "http://127.0.0.1:8000";
    return [
      { source: "/api/:path*", destination: `${target}/api/:path*` },
      { source: "/health", destination: `${target}/health` },
    ];
  },
};

export default nextConfig;
