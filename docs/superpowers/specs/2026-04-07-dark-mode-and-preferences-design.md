# Dark Mode & Preferences in Profile Page

## Summary

Enable dark mode switching and consolidate user preferences (language + theme) into the Settings → Profile page. Remove the language switcher from the sidebar dropdown menu.

## Current State

- **Dark mode infrastructure exists** but is force-locked:
  - `globals.css` has complete `:root/.light` and `.dark` CSS token sets
  - `tailwind.config.ts` uses `darkMode: ['class']`
  - `next-themes` ThemeProvider configured with `forcedTheme="light"` and `enableSystem={false}`
  - Zustand store has `theme: 'light' | 'dark' | 'system'` field
  - `syncThemeToNextThemes()` utility exists in `lib/core/utils/theme.ts`
  - `fetchGeneralSettings()` hardcodes `theme: 'dark' as const`, ignoring API response
- **Language switcher** lives in sidebar user dropdown (`components/app-sidebar/user-info.tsx`) as a sub-menu
- **Profile page** (`components/settings/profile-page.tsx`) contains only avatar/name editing, logout, and reset password

## Changes

### 1. Unlock dark mode in ThemeProvider

**File:** `providers/theme-provider.tsx`

- Remove `forcedTheme="light"`
- Set `enableSystem={true}`
- Change `defaultTheme` to `"system"`

### 2. Remove hardcoded theme in general-settings query

**File:** `hooks/queries/general-settings.ts`

- In `fetchGeneralSettings()`, change `theme: 'dark' as const` to `theme: data.theme ?? 'system'` so the API value is respected with a `'system'` fallback

### 3. Add Preferences section to Profile page

**File:** `components/settings/profile-page.tsx`

Add a new "Preferences" section below the Action Buttons area:

```
──────────────────────────
Preferences
  Language:  [Select: English / 中文]
  Theme:     [Light | Dark | System]  (segmented toggle group)
──────────────────────────
```

**Language selector:**
- Use a shadcn `Select` component with two options (English, 中文)
- On change, call `i18n.changeLanguage(langCode)`
- Display current language as selected value

**Theme selector:**
- Use a segmented control / `ToggleGroup` with three options: Light, Dark, System
- Each option shows an icon (Sun, Moon, Monitor) + label
- On change, call `setTheme()` from `next-themes` `useTheme()` hook
- Instant effect, no save button needed

### 4. Remove language switcher from sidebar dropdown

**File:** `components/app-sidebar/user-info.tsx`

- Remove the `DropdownMenuSub` block for language switching
- Remove the `Languages` icon import and `languages` array
- Remove `handleLanguageChange` function
- Keep Settings, Logout menu items

### 5. Add i18n translation keys

**Files:** `lib/i18n/locales/en.ts`, `lib/i18n/locales/zh.ts`

New keys under `settings`:
- `settings.preferences` — "Preferences" / "偏好设置"
- `settings.theme` — "Theme" / "主题"
- `settings.themeLight` — "Light" / "浅色"
- `settings.themeDark` — "Dark" / "深色"
- `settings.themeSystem` — "System" / "跟随系统"

## Files Changed (Summary)

| File | Change |
|------|--------|
| `providers/theme-provider.tsx` | Remove `forcedTheme`, enable system |
| `hooks/queries/general-settings.ts` | Remove hardcoded theme |
| `components/settings/profile-page.tsx` | Add Preferences section |
| `components/app-sidebar/user-info.tsx` | Remove language sub-menu |
| `lib/i18n/locales/en.ts` | Add translation keys |
| `lib/i18n/locales/zh.ts` | Add translation keys |

## Out of Scope

- Persisting theme preference to backend API (current localStorage via next-themes is sufficient)
- Animated theme transitions (kept disabled via `disableTransitionOnChange`)
- Per-component dark mode overrides — all components already use CSS variables that respond to `.dark` class
