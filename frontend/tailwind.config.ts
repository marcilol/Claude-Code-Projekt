import type { Config } from "tailwindcss";

export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        // Sampled from aibottlenecks.app — warm cream palette
        cream: {
          50: "#fbf7ee",  // lightest card surface
          100: "#f5ede0", // page background
          200: "#ede2cf", // subtle alt bg
          300: "#e8ddc9", // border
          400: "#d4c4a6", // hover/disabled
        },
        ink: {
          900: "#1a1f24", // primary text
          700: "#3d4148", // secondary text
          500: "#6b6b6b", // muted
          400: "#9a8f7d", // tan-grey muted
        },
        forest: {
          // Dark teal/forest — primary accent (active pills, headers)
          900: "#102b26",
          800: "#1a3d36",
          700: "#245349",
          600: "#2e6b5e",
        },
        // Semantic
        positive: "#2d8659",
        negative: "#c8424a",
      },
      fontFamily: {
        sans: [
          "Inter",
          "ui-sans-serif",
          "system-ui",
          "-apple-system",
          "Segoe UI",
          "Roboto",
          "sans-serif",
        ],
      },
    },
  },
  plugins: [],
} satisfies Config;
