/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  // Ship only the minimal server + traced dependencies in the Docker image
  // instead of the full node_modules tree -- smaller image, faster cold
  // start and faster `npm start` boot on Render's free tier.
  output: "standalone",
};
export default nextConfig;
