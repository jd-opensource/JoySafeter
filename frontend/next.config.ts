import type { NextConfig } from 'next'

const nextConfig: NextConfig = {
  async redirects() {
    return [
      {
        source: '/workspace/:path*',
        destination: '/agents',
        permanent: true,
      },
    ]
  },
  devIndicators: false,
  output: 'standalone',
  // Next config is loaded by Node; path.join is standard
  // eslint-disable-next-line @typescript-eslint/no-require-imports
  outputFileTracingRoot: require('path').join(__dirname),
  images: {
    remotePatterns: [
      {
        protocol: 'https',
        hostname: 'avatars.githubusercontent.com',
      },
    ],
  },
  turbopack: {
    resolveExtensions: ['.tsx', '.ts', '.jsx', '.js', '.mjs', '.json'],
  },
  experimental: {
    optimizeCss: true,
  },
}

export default nextConfig
