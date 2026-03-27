export type LanguageCode = "en" | "pl" | "es" | "pt" | "fr" | "ru";

export type UIStrings = {
  title: string;
  extractTitle: string;
  extractButton: string;
  parserLabel: string;
  parserPypdfOption: string;
  parserGeminiOption: string;
  parserMistralOption: string;
  extractMultiHint: string;
  selectedFilesLabel: string;
  extractStatusIdle: string;
  extractStatusRunning: string;
  extractStatusDone: (cached: boolean) => string;
  geminiTitle: string;
  interfaceLanguageLabel: string;
  promptPlaceholder: string;
  askButton: string;
  statusTitle: string;
  errorPrefix: string;
  extractResultTitle: string;
  sha256Label: string;
  cachedLabel: string;
  geminiAnswerTitle: string;
  geminiStatusRunning: string;
  geminiStatusDone: string;
  noPromptStatus: string;
};
