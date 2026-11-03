// 운영: 정적 파일(out/)로 빌드해 nginx 가 서빙한다. /api 와 /guacamole 은 nginx 가 프록시.
// 개발: `npm run dev` 시 /api 를 로컬 백엔드(기본 http://localhost:8000)로 넘긴다.
const isDev = process.env.NODE_ENV !== "production";
const apiTarget = process.env.JARION_API_URL || "http://localhost:8000";

/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  trailingSlash: true,
  ...(isDev
    ? {
        async rewrites() {
          return [{ source: "/api/:path*", destination: `${apiTarget}/api/:path*` }];
        },
      }
    : { output: "export" }),
};

export default nextConfig;
