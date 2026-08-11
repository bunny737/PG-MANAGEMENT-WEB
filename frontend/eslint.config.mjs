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
          "jsx-attributes": {
            exclude: [
              "className",
              "styleName",
              "style",
              "type",
              "key",
              "id",
              "width",
              "height",
              "href",
              "aria-current",
              "aria-hidden",
              "aria-label",
              "alt",
              "value",
              "src",
              "name",
              "variant",
              "size",
              "tone",
              "target",
              "rel",
              "role",
              "htmlFor",
              "autoComplete",
              "dot",
            ],
          },
          "object-properties": {
            exclude: [".*"],
          },
          callees: {
            exclude: [
              "i18n(ext)?",
              "t.*",
              "t",
              "require",
              "addEventListener",
              "removeEventListener",
              "postMessage",
              "getElementById",
              "dispatch",
              "commit",
              "includes",
              "indexOf",
              "endsWith",
              "startsWith",
            ],
          },
        },
      ],
    },
  },
  {
    files: ["src/**"],
    rules: {
      "i18next/no-literal-string": [
        "error",
        {
          mode: "jsx-only",
          "only-jsx-components": true,
          "jsx-attributes": {
            exclude: [
              "className",
              "styleName",
              "style",
              "type",
              "key",
              "id",
              "width",
              "height",
              "href",
              "aria-current",
              "aria-hidden",
              "aria-label",
              "alt",
              "value",
              "src",
              "name",
              "variant",
              "size",
              "tone",
              "target",
              "rel",
              "role",
              "htmlFor",
              "autoComplete",
              "dot",
            ],
          },
          "object-properties": {
            exclude: [".*"],
          },
          callees: {
            exclude: [
              "i18n(ext)?",
              "t.*",
              "t",
              "require",
              "addEventListener",
              "removeEventListener",
              "postMessage",
              "getElementById",
              "dispatch",
              "commit",
              "includes",
              "indexOf",
              "endsWith",
              "startsWith",
            ],
          },
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
