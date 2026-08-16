/** @type {import("next").NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  // The shared packages are consumed as TypeScript source rather than as
  // built output, so Next has to compile them alongside the app.
  transpilePackages: ["@pretrial/shared-types", "@pretrial/fhir-client"],
  eslint: {
    ignoreDuringBuilds: false,
  },
  async headers() {
    return [
      {
        source: "/:path*",
        headers: [
          { key: "X-Content-Type-Options", value: "nosniff" },
          { key: "X-Frame-Options", value: "DENY" },
          { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },
        ],
      },
    ];
  },
};

export default nextConfig;
