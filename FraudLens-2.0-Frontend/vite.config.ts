import { tanstackStart } from "@tanstack/react-start/plugin/vite";
import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { nitro } from "nitro/vite";
import svgr from "vite-plugin-svgr";
import { createRunnableDevEnvironment, defineConfig } from "vite";
import tsconfigPaths from "vite-tsconfig-paths";

export default defineConfig(({ command }) => ({
  preview: {
    allowedHosts: true,
  },

  environments: {
    ssr: {
      dev: {
        createEnvironment: (name, config) =>
          createRunnableDevEnvironment(name, config),
      },
    },
  },

  plugins: [
    svgr({
      svgrOptions: {
        icon: true,
        svgProps: { fill: "currentColor" },
        svgoConfig: {
          plugins: [
            {
              name: "preset-default",
              params: { overrides: { removeViewBox: false } },
            },
          ],
        },
      },
    }),
    tanstackStart({
      server: { entry: "server" },
      vite: { installDevServerMiddleware: true },
    }),
    ...(command === 'build' ? [nitro()] : []),
    react(),
    tailwindcss(),
    tsconfigPaths(),
  ],
}));
