import { defineConfig, globalIgnores } from "eslint/config";
import nextVitals from "eslint-config-next/core-web-vitals";
import nextTs from "eslint-config-next/typescript";
import i18nextPlugin from "eslint-plugin-i18next";

const eslintConfig = defineConfig([
  ...nextVitals,
  ...nextTs,
  {
    plugins: {
      i18next: i18nextPlugin,
    },
    rules: {
      "i18next/no-literal-string": [
        "warn",
        {
          mode: "jsx-only",
          "only-jsx-components": true,
        },
      ],
    },
  },
  globalIgnores([
    ".next/**",
    "out/**",
    "build/**",
    "next-env.d.ts",
    "src/i18n/config.ts",
    "**/mock-*.ts",
  ]),
]);

export default eslintConfig;
