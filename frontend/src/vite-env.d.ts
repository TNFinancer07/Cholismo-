/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_OPERATOR?: string
  readonly VITE_API_BASE?: string
}

interface ImportMeta {
  readonly env: ImportMetaEnv
}
