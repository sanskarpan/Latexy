/** @type {import('next').NextConfig} */
const nextConfig = {
    webpack: (config) => {
      // Handle canvas for react-pdf
      config.resolve.alias.canvas = false;
      config.resolve.alias.encoding = false;
      return config;
    },
  }
  
  module.exports = nextConfig