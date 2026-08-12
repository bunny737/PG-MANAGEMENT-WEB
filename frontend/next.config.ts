import type { NextConfig } from "next";
import createNextIntlPlugin from "next-intl/plugin";
import path from "path";

const withNextIntl = createNextIntlPlugin();

const nextConfig: NextConfig = {
  webpack: (config, { dev }) => {
    if (dev) {
      config.watchOptions = {
        poll: 1000,
        aggregateTimeout: 300,
      };
    }

    // Ensure next-intl/config alias is accurately resolved across both Webpack and Turbopack on Windows
    const requestConfigPath = path.resolve(__dirname, "src/i18n/request.ts");
    config.resolve = config.resolve || {};
    config.resolve.alias = config.resolve.alias || {};
    config.resolve.alias["next-intl/config$"] = requestConfigPath;
    config.resolve.alias["next-intl/config"] = requestConfigPath;

    return config;
  },
};

export default withNextIntl(nextConfig);


