import type { NextConfig } from "next";

/**
 * Requests to /api are proxied to the Python API, so the browser talks to one
 * origin and the scientific system stays the only source of truth. Point
 * BACTERION_API_URL at the FastAPI server if it is not on the default port.
 */
const apiUrl = process.env.BACTERION_API_URL ?? "http://127.0.0.1:8000";

const nextConfig: NextConfig = {
  async rewrites() {
    return [{ source: "/api/:path*", destination: `${apiUrl}/api/:path*` }];
  },
};

export default nextConfig;
