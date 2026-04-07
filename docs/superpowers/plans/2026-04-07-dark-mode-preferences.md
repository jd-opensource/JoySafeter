# Dark Mode & Preferences Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Unlock dark mode and add a Preferences section (language + theme) to the Settings Profile page.

**Architecture:** Remove the force-lock on next-themes, standardize theme sync through next-themes' `setTheme()`, add a Preferences UI block to the existing Profile page, and clean up the sidebar language switcher.

**Tech Stack:** Next.js 16, React 19, next-themes, shadcn/ui (Radix), Tailwind CSS, Zustand, i18next

**Spec:** `docs/superpowers/specs/2026-04-07-dark-mode-and-preferences-design.md`

> All file paths are relative to `frontend/`.

---

### Task 1: Unlock dark mode in ThemeProvider

**Files:**
- Modify: `providers/theme-provider.tsx`

- [ ] **Step 1: Update ThemeProvider props**

Remove `forcedTheme="light"`, set `enableSystem={true}`, change `defaultTheme` to `"system"`:

```tsx
export function ThemeProvider({ children, ...props }: ThemeProviderProps) {
  return (
    <NextThemesProvider
      attribute="class"
      defaultTheme="system"
      enableSystem
      disableTransitionOnChange
      storageKey="joysafeter-theme"
      {...props}
    >
      {children}
    </NextThemesProvider>
  )
}
```

- [ ] **Step 2: Verify the app loads without errors**

Run: `cd frontend && bun run build`
Expected: Build succeeds with no errors.

- [ ] **Step 3: Commit**

```bash
git add frontend/providers/theme-provider.tsx
git commit -m "feat: unlock dark mode in ThemeProvider"
```

---

### Task 2: Fix Zustand store default and remove hardcoded theme

**Files:**
- Modify: `stores/settings/general/store.ts`
- Modify: `hooks/queries/general-settings.ts`

- [ ] **Step 1: Change Zustand store default theme from `'dark'` to `'system'`**

In `stores/settings/general/store.ts`, change line 23:

```ts
// Before:
theme: 'dark',
// After:
theme: 'system',
```

- [ ] **Step 2: Remove hardcoded theme in fetchGeneralSettings**

In `hooks/queries/general-settings.ts`, change line 52:

```ts
// Before:
theme: 'dark' as const,
// After:
theme: data.theme ?? 'system',
```

- [ ] **Step 3: Commit**

```bash
git add frontend/stores/settings/general/store.ts frontend/hooks/queries/general-settings.ts
git commit -m "fix: use system as default theme, respect API response"
```

---

### Task 3: Refactor theme sync to work with unlocked next-themes

**Files:**
- Modify: `lib/core/utils/theme.ts`
- Modify: `hooks/queries/general-settings.ts`

**Note:** The spec says to use next-themes' `setTheme()` directly, but `syncThemeToNextThemes()` is called from `syncSettingsToZustand()` which runs outside a React component (no hook access). The pragmatic approach: write to localStorage and dispatch a StorageEvent so next-themes picks up the change. This achieves the same result without requiring a hook context.

- [ ] **Step 1: Rewrite syncThemeToNextThemes to use localStorage + StorageEvent**

The function currently manually toggles HTML classes. Since next-themes is now unlocked and listens to its `storageKey`, we only need to write to localStorage and dispatch a storage event — next-themes handles the rest. Replace the entire function:

```ts
/**
 * Sync theme to next-themes by updating localStorage.
 * next-themes listens for storage events and applies the class automatically.
 *
 * @param theme - The theme to set ('light' | 'dark' | 'system')
 */
export function syncThemeToNextThemes(theme: 'light' | 'dark' | 'system'): void {
  if (typeof window === 'undefined') {
    return
  }

  try {
    const storageKey = 'joysafeter-theme'

    if (theme === 'system') {
      localStorage.setItem(storageKey, 'system')
    } else {
      localStorage.setItem(storageKey, theme)
    }

    // Trigger next-themes to pick up the change
    window.dispatchEvent(
      new StorageEvent('storage', {
        key: storageKey,
        newValue: theme,
        storageArea: localStorage,
      }),
    )
  } catch (error) {
    console.error('Failed to sync theme to next-themes:', error)
  }
}
```

- [ ] **Step 2: Update comment in syncSettingsToZustand**

In `hooks/queries/general-settings.ts`, update the comment above `syncThemeToNextThemes` call (line 77) to clarify the mechanism:

```ts
// Before:
  syncThemeToNextThemes(settings.theme)
// After:
  // Sync theme via localStorage — next-themes picks up the change automatically
  syncThemeToNextThemes(settings.theme)
```

- [ ] **Step 3: Commit**

```bash
git add frontend/lib/core/utils/theme.ts frontend/hooks/queries/general-settings.ts
git commit -m "refactor: simplify theme sync to work with unlocked next-themes"
```

---

### Task 4: Add i18n translation keys

**Files:**
- Modify: `lib/i18n/locales/en.ts`
- Modify: `lib/i18n/locales/zh.ts`

- [ ] **Step 1: Add keys to en.ts**

Inside the `settings` object (after the existing keys like `general`, around line 88), add:

```ts
preferences: 'Preferences',
theme: 'Theme',
themeLight: 'Light',
themeDark: 'Dark',
themeSystem: 'System',
```

- [ ] **Step 2: Add keys to zh.ts**

Inside the `settings` object (same location), add:

```ts
preferences: '偏好设置',
theme: '主题',
themeLight: '浅色',
themeDark: '深色',
themeSystem: '跟随系统',
```

- [ ] **Step 3: Commit**

```bash
git add frontend/lib/i18n/locales/en.ts frontend/lib/i18n/locales/zh.ts
git commit -m "feat: add i18n keys for preferences, theme"
```

---

### Task 5: Install toggle-group and create shadcn component

**Files:**
- Create: `components/ui/toggle-group.tsx`

- [ ] **Step 1: Install @radix-ui/react-toggle-group**

```bash
cd frontend && bun add @radix-ui/react-toggle-group
```

- [ ] **Step 2: Create toggle-group.tsx**

Create `components/ui/toggle-group.tsx` following the project's shadcn pattern (matching `toggle.tsx` style):

```tsx
'use client'

import * as ToggleGroupPrimitive from '@radix-ui/react-toggle-group'
import { type VariantProps } from 'class-variance-authority'
import * as React from 'react'

import { cn } from '@/lib/utils'

import { toggleVariants } from './toggle'

const ToggleGroupContext = React.createContext<VariantProps<typeof toggleVariants>>({
  size: 'default',
  variant: 'default',
})

const ToggleGroup = React.forwardRef<
  React.ElementRef<typeof ToggleGroupPrimitive.Root>,
  React.ComponentPropsWithoutRef<typeof ToggleGroupPrimitive.Root> &
    VariantProps<typeof toggleVariants>
>(({ className, variant, size, children, ...props }, ref) => (
  <ToggleGroupPrimitive.Root
    ref={ref}
    className={cn('flex items-center justify-center gap-1', className)}
    {...props}
  >
    <ToggleGroupContext.Provider value={{ variant, size }}>
      {children}
    </ToggleGroupContext.Provider>
  </ToggleGroupPrimitive.Root>
))
ToggleGroup.displayName = ToggleGroupPrimitive.Root.displayName

const ToggleGroupItem = React.forwardRef<
  React.ElementRef<typeof ToggleGroupPrimitive.Item>,
  React.ComponentPropsWithoutRef<typeof ToggleGroupPrimitive.Item> &
    VariantProps<typeof toggleVariants>
>(({ className, children, variant, size, ...props }, ref) => {
  const context = React.useContext(ToggleGroupContext)

  return (
    <ToggleGroupPrimitive.Item
      ref={ref}
      className={cn(
        toggleVariants({
          variant: variant || context.variant,
          size: size || context.size,
        }),
        className,
      )}
      {...props}
    >
      {children}
    </ToggleGroupPrimitive.Item>
  )
})
ToggleGroupItem.displayName = ToggleGroupPrimitive.Item.displayName

export { ToggleGroup, ToggleGroupItem }
```

- [ ] **Step 3: Verify build**

Run: `cd frontend && bun run build`
Expected: Build succeeds.

- [ ] **Step 4: Commit**

```bash
git add frontend/components/ui/toggle-group.tsx frontend/package.json frontend/bun.lock
git commit -m "feat: add toggle-group shadcn component"
```

---

### Task 6: Add Preferences section to Profile page

**Files:**
- Modify: `components/settings/profile-page.tsx`

- [ ] **Step 1: Add imports**

Add these imports at the top of `profile-page.tsx`:

```tsx
import { Sun, Moon, Monitor } from 'lucide-react'
import { useTheme } from 'next-themes'

import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { ToggleGroup, ToggleGroupItem } from '@/components/ui/toggle-group'
```

- [ ] **Step 2: Add theme hook and language handler inside ProfilePage component**

After the existing state declarations (around line 105), add:

```tsx
const { theme, setTheme } = useTheme()
const { i18n } = useTranslation() // already destructured t above, add i18n
```

Update the existing `useTranslation()` destructure to include `i18n`:

```tsx
// Before:
const { t } = useTranslation()
// After:
const { t, i18n } = useTranslation()
```

- [ ] **Step 3: Add Preferences section JSX**

After the `{/* Action Buttons */}` section's closing `</div>` (after line 314), add:

```tsx
{/* Preferences */}
<div className="space-y-4 border-t border-border pt-6">
  <h3 className="text-sm font-semibold text-[var(--text-primary)]">
    {t('settings.preferences')}
  </h3>
  <div className="flex flex-wrap items-center gap-4">
  <div className="flex items-center gap-3">
    <span className="text-sm font-medium text-[var(--text-secondary)]">
      {t('common.language')}
    </span>
    <Select value={i18n.language} onValueChange={(val) => i18n.changeLanguage(val)}>
      <SelectTrigger className="w-[140px]">
        <SelectValue />
      </SelectTrigger>
      <SelectContent>
        <SelectItem value="en">English</SelectItem>
        <SelectItem value="zh">中文</SelectItem>
      </SelectContent>
    </Select>
  </div>

  <div className="flex items-center gap-3">
    <span className="text-sm font-medium text-[var(--text-secondary)]">
      {t('settings.theme')}
    </span>
    <ToggleGroup
      type="single"
      value={theme}
      onValueChange={(val) => { if (val) setTheme(val) }}
      className="rounded-lg border border-[var(--border)] p-0.5"
    >
      <ToggleGroupItem value="light" aria-label={t('settings.themeLight')} className="gap-1.5 px-3 text-xs">
        <Sun size={14} />
        {t('settings.themeLight')}
      </ToggleGroupItem>
      <ToggleGroupItem value="dark" aria-label={t('settings.themeDark')} className="gap-1.5 px-3 text-xs">
        <Moon size={14} />
        {t('settings.themeDark')}
      </ToggleGroupItem>
      <ToggleGroupItem value="system" aria-label={t('settings.themeSystem')} className="gap-1.5 px-3 text-xs">
        <Monitor size={14} />
        {t('settings.themeSystem')}
      </ToggleGroupItem>
    </ToggleGroup>
  </div>
  </div>
</div>
```

- [ ] **Step 4: Fix hardcoded light-mode colors in reset password dialog**

In the reset password dialog icon container (around line 321), change:

```tsx
// Before:
<div className="shrink-0 rounded-lg border border-[var(--surface-1)] bg-violet-50 p-1.5 text-violet-600 shadow-sm">
// After:
<div className="shrink-0 rounded-lg border border-[var(--surface-1)] bg-violet-50 p-1.5 text-violet-600 shadow-sm dark:bg-violet-900/30 dark:text-violet-400">
```

- [ ] **Step 5: Verify build**

Run: `cd frontend && bun run build`
Expected: Build succeeds.

- [ ] **Step 6: Commit**

```bash
git add frontend/components/settings/profile-page.tsx
git commit -m "feat: add language and theme preferences to profile page"
```

---

### Task 7: Remove language switcher from sidebar dropdown

**Files:**
- Modify: `components/app-sidebar/user-info.tsx`

- [ ] **Step 1: Clean up imports**

Remove unused imports:

```tsx
// Remove from lucide-react import:
Languages, Check

// Remove these dropdown imports:
DropdownMenuSub,
DropdownMenuSubContent,
DropdownMenuSubTrigger,
```

Also remove the `useTranslation` destructure of `i18n` (keep only `t`):

```tsx
// Before:
const { t, i18n } = useTranslation()
// After:
const { t } = useTranslation()
```

- [ ] **Step 2: Remove language-related code**

Delete the `languages` array (lines 48-51):

```tsx
// DELETE:
const languages = [
  { code: 'en', label: 'English' },
  { code: 'zh', label: '中文' },
]
```

Delete `handleLanguageChange` function (lines 78-80):

```tsx
// DELETE:
const handleLanguageChange = (langCode: string) => {
  i18n.changeLanguage(langCode)
}
```

- [ ] **Step 3: Remove language sub-menu from dropdown**

Delete the entire `DropdownMenuSub` block (lines 131-154) and the `DropdownMenuSeparator` immediately after it (line 156). The dropdown should go directly from the user info section to the Settings item.

- [ ] **Step 4: Verify build**

Run: `cd frontend && bun run build`
Expected: Build succeeds.

- [ ] **Step 5: Commit**

```bash
git add frontend/components/app-sidebar/user-info.tsx
git commit -m "refactor: remove language switcher from sidebar dropdown"
```

---

### Task 8: Final verification

- [ ] **Step 1: Full build check**

```bash
cd frontend && bun run build
```

Expected: Build succeeds with no errors.

- [ ] **Step 2: Lint check**

```bash
cd frontend && bun run lint
```

Expected: No lint errors.

- [ ] **Step 3: Manual smoke test checklist**

Verify in browser:
- [ ] App loads in system theme by default
- [ ] Settings → Profile shows Preferences section with Language and Theme
- [ ] Theme toggle switches between Light / Dark / System instantly
- [ ] Language selector switches between English / 中文
- [ ] Sidebar dropdown no longer shows language sub-menu
- [ ] Dark mode renders correctly (CSS variables switch, no broken colors)
- [ ] Reset password dialog icon looks correct in both themes
