/** @type {import('next').NextConfig} */
const nextConfig = {
  // Only enable static export for production builds
  // Development mode uses Next.js dev server (supports dynamic routes)
  ...(process.env.ELECTRON_BUILD === 'true' ? { output: 'export' } : {}),

  // Disable image optimization for static export
  images: {
    unoptimized: true,
  },

  // Trailing slash for better compatibility
  trailingSlash: true,

  // Disable server-side features
  reactStrictMode: true,

  webpack: (config) => {
    config.resolve.alias.canvas = false;
    return config;
  },
};

module.exports = nextConfig;
