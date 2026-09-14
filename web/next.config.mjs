/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  // The agent key must never reach the browser bundle: every call to the API
  // goes through a server action or a route handler.
  serverExternalPackages: [],
};

export default nextConfig;
