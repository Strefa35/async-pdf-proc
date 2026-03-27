import { en } from "./en";
import { es } from "./es";
import { fr } from "./fr";
import { pl } from "./pl";
import { pt } from "./pt";
import { ru } from "./ru";
import { LanguageCode, UIStrings } from "./types";

export const UI_STRINGS: Record<LanguageCode, UIStrings> = {
  en,
  pl,
  es,
  pt,
  fr,
  ru,
};

export const LANGUAGE_OPTIONS: Array<{ value: LanguageCode; label: string }> = [
  { value: "en", label: "English" },
  { value: "pl", label: "Polski" },
  { value: "es", label: "Español" },
  { value: "pt", label: "Português" },
  { value: "fr", label: "Français" },
  { value: "ru", label: "Русский" },
];
