# Dark Mode & Preferences in Profile Page

> All file paths below are relative to `frontend/`.

## Summary

Enable dark mode switching and consolidate user preferences (language + theme) into the Settings → Profile page. Remove the language switcher from the sidebar dropdown menu.

## Current State

- **Dark mode infrastructure exists** but is force-locked:
  - `globals.css` has complete `:root/.light` and `.dark` CSS token sets
  - `tailwind.config.ts` uses `darkMode: ['class']`
  - `next-themes` ThemeProvider configured with `forcedTheme="light"` and `enableSystem={false}`
  - Zustand store has `theme: 'light' | 'dark' | 'system'` field (default: `'dark'`)
  - `syncThemeToNextThemes()` utility exists in `lib/core/utils/theme.ts` — manually writes to localStorage and toggles HTML classes, bypassing next-themes internal state
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

### 3. Update Zustand store default

**File:** `stores/settings/general/store.ts`

- Change default `theme` from `'dark'` to `'system'` to match the ThemeProvider default and avoid a flash of dark mode before query data arrives

### 4. Standardize theme sync on next-themes `setTheme()`

**File:** `lib/core/utils/theme.ts`

- Refactor `syncThemeToNextThemes()` to use next-themes' own `setTheme()` mechanism instead of manually manipulating localStorage and HTML classes. This avoids dual-write conflicts between the query sync path and the profile page UI.

**File:** `hooks/queries/general-settings.ts`

- Update `syncSettingsToZustand()` to use the refactored utility consistently

### 5. Add Preferences section to Profile page

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
- Use the existing shadcn `Select` component with two options (English, 中文)
- Label uses existing `t('common.language')` key
- On change, call `i18n.changeLanguage(langCode)`
- Display current language as selected value

**Theme selector:**
- Install `@radix-ui/react-toggle-group` and generate shadcn `components/ui/toggle-group.tsx`
- Three options: Light (Sun icon), Dark (Moon icon), System (Monitor icon)
- On change, call `setTheme()` from `next-themes` `useTheme()` hook
- Instant effect, no save button needed

**Dark mode color fixes in profile page:**
- Replace hardcoded `bg-violet-50 text-violet-600` in the reset password dialog icon with dark-aware variants (e.g., `bg-violet-50 dark:bg-violet-900/30 text-violet-600 dark:text-violet-400`)

### 6. Remove language switcher from sidebar dropdown

**File:** `components/app-sidebar/user-info.tsx`

- Remove the `DropdownMenuSub` block for language switching
- Remove the `Languages`, `Check` icon imports and `languages` array
- Remove `handleLanguageChange` function
- Remove unused imports: `DropdownMenuSub`, `DropdownMenuSubContent`, `DropdownMenuSubTrigger`
- Keep Settings, Logout menu items

### 7. Add i18n translation keys

**Files:** `lib/i18n/locales/en.ts`, `lib/i18n/locales/zh.ts`

New keys under `settings`:
- `settings.preferences` — "Preferences" / "偏好设置"
- `settings.theme` — "Theme" / "主题"
- `settings.themeLight` — "Light" / "浅色"
- `settings.themeDark` — "Dark" / "深色"
- `settings.themeSystem` — "System" / "跟随系统"

Language label reuses existing `common.language` key.

## Files Changed (Summary)

| File | Change |
|------|--------|
| `providers/theme-provider.tsx` | Remove `forcedTheme`, enable system |
| `hooks/queries/general-settings.ts` | Remove hardcoded theme, update sync |
| `stores/settings/general/store.ts` | Change default theme to `'system'` |
| `lib/core/utils/theme.ts` | Refactor to use next-themes `setTheme()` |
| `components/settings/profile-page.tsx` | Add Preferences section, fix hardcoded colors |
| `components/ui/toggle-group.tsx` | New shadcn component (generated) |
| `components/app-sidebar/user-info.tsx` | Remove language sub-menu |
| `lib/i18n/locales/en.ts` | Add translation keys |
| `lib/i18n/locales/zh.ts` | Add translation keys |

## Dependencies to Install

- `@radix-ui/react-toggle-group` (for the theme segmented control)

## Out of Scope

- Persisting theme preference to backend API (current localStorage via next-themes is sufficient)
- Animated theme transitions (kept disabled via `disableTransitionOnChange`)
- Comprehensive dark mode audit of all components (most use CSS variables; the profile page hardcoded colors are fixed in this spec)
