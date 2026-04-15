# Localization Guide

This guide explains how to modify existing translations and how to add a new language.

Current localization files are stored in:

- `frontend/src/locales/`

---

## 1. File Structure

Localization is split into:

- `frontend/src/locales/types.ts`
  - shared types (`LanguageCode`, `UIStrings`)
- `frontend/src/locales/<lang>.ts`
  - one file per language (for example `en.ts`, `pl.ts`)
- `frontend/src/locales/index.ts`
  - exports `UI_STRINGS`
  - defines `LANGUAGE_OPTIONS` used by the UI selector

---

## 2. Edit an Existing Language

1. Open the language file, for example:
   - `frontend/src/locales/en.ts`
2. Update text values in the exported object.
3. Keep all keys present (must match `UIStrings` type).
4. Save and refresh frontend.

Tip: If one key is missing or has wrong type, TypeScript should report an error.

---

## 3. Add a New Language

Example: adding German (`de`).

### Step 1: Create a language file

Create:

- `frontend/src/locales/de.ts`

Use the template from:

- `frontend/src/locales/template.ts`

### Step 2: Extend language code type

Update `frontend/src/locales/types.ts`:

```ts
export type LanguageCode = "en" | "pl" | "es" | "pt" | "fr" | "ru" | "de";
```

### Step 3: Register language in index

Update `frontend/src/locales/index.ts`:

1. Import the language:

```ts
import { de } from "./de";
```

2. Add it to `UI_STRINGS`:

```ts
de,
```

3. Add selector option:

```ts
{ value: "de", label: "Deutsch" },
```

### Step 4: Rebuild and test

```bash
# From the repository root (directory containing docker-compose.yml)
docker compose up -d --build --force-recreate frontend
```

Then verify:

- language appears in dropdown,
- interface labels are translated,
- Gemini still receives selected language code.

---

## 4. Translation Rules

- Keep keys exactly as defined in `UIStrings`.
- Keep placeholders and dynamic formatting behavior.
- `extractStatusDone` must remain a function:
  - `(cached: boolean) => string`
- Use plain text (avoid unnecessary HTML).
- Prefer concise labels for buttons and section titles.

---

## 5. Validation Checklist

- New file exports a valid `UIStrings` object.
- `LanguageCode` includes new code.
- `index.ts` includes import + map entry + dropdown option.
- Frontend starts without TypeScript errors.
- UI renders correctly after selection.

---

**Async PDF Processor** v.0.0.2 · 14 April 2026 · Code author: Arkadiusz Czerwinski
