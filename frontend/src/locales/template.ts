import { UIStrings } from "./types";

/**
 * Template for creating a new locale file.
 *
 * Usage:
 * 1) Copy this file to <lang>.ts (for example: de.ts)
 * 2) Rename `templateLocale` to your language code constant (for example: de)
 * 3) Replace all strings with target language translations
 * 4) Register the locale in `frontend/src/locales/index.ts`
 */
export const templateLocale: UIStrings = {
  title: "Async PDF Processor",
  extractTitle: "1) Extract text from PDF",
  extractButton: "Extract",
  parserLabel: "Parser:",
  parserPypdfOption: "PyPDF (text)",
  parserGeminiOption: "Gemini 2.5 Flash (markdown)",
  parserMistralOption: "Mistral (markdown)",
  extractMultiHint: "You can select multiple PDF files (Ctrl/Shift in file picker).",
  selectedFilesLabel: "Selected files",
  extractStatusIdle: "Choose a PDF file and click Extract.",
  extractStatusRunning: "Extracting PDF...",
  extractStatusDone: (cached) => `Extract done (cached=${String(cached)}).`,
  geminiTitle: "2) Ask Gemini 2.5 Flash",
  interfaceLanguageLabel: "Interface language:",
  promptPlaceholder: "Ask a question based on the PDF...",
  askButton: "Ask Gemini",
  statusTitle: "Status",
  errorPrefix: "Error",
  extractResultTitle: "Extract result",
  sha256Label: "sha256",
  cachedLabel: "cached",
  geminiAnswerTitle: "Gemini answer",
  geminiStatusRunning: "Gemini: working...",
  geminiStatusDone: "Gemini: done.",
  noPromptStatus: "Type a question first.",
};
