/**
 * Test-only helpers for asserting i18n coverage. Kept framework-free (no vitest
 * import) so any test runner can use them. Lets locale-contract tests resolve a
 * dotted key against the actual en/zh trees and extract ``{{placeholder}}``
 * names, so a presenter that points at a missing key or a template whose
 * placeholders drift from the data contract fails loudly.
 */
import en from './locales/en'
import zh from './locales/zh'

export const enTree = en.translation as unknown as Record<string, unknown>
export const zhTree = zh.translation as unknown as Record<string, unknown>

/** Resolve a dotted i18n key against a locale tree; undefined if any segment is missing. */
export function resolveKey(tree: Record<string, unknown>, key: string): string | undefined {
  let node: unknown = tree
  for (const seg of key.split('.')) {
    if (node && typeof node === 'object' && seg in (node as Record<string, unknown>)) {
      node = (node as Record<string, unknown>)[seg]
    } else {
      return undefined
    }
  }
  return typeof node === 'string' ? node : undefined
}

/** Extract the set of ``{{name}}`` interpolation placeholders from a template string. */
export function placeholders(template: string): Set<string> {
  return new Set([...template.matchAll(/\{\{\s*(\w+)\s*\}\}/g)].map((m) => m[1]))
}
