import type { NextConfig } from "next";

const api = process.env.API_INTERNAL_URL || "http://127.0.0.1:8000";

const nextConfig: NextConfig = {
  output: "standalone",
  allowedDevOrigins: ["localhost", "127.0.0.1"],
  async rewrites() {
    return [
      { source: "/api/:path*", destination: `${api}/api/:path*` },
      { source: "/d/:path*", destination: `${api}/d/:path*` },
      { source: "/p/:path*", destination: `${api}/p/:path*` },
      { source: "/office-files/:path*", destination: `${api}/office-files/:path*` },
    ];
  },
};

export default nextConfig;
