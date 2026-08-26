import { readdirSync, readFileSync } from 'node:fs'
import path from 'node:path'

import ts from 'typescript'
import { describe, expect, it } from 'vitest'

const TEST_FILE_PATTERN = /\.(?:test|spec)\.(?:ts|tsx)$/
const SOURCE_FILE_PATTERN = /\.(?:ts|tsx)$/
const QUOTED_CORE_ID_PATTERN =
  /["'`]((?:agent_|sess_|task_|trig_|env_|secret_|vault_|cred_|sbx_|memstore_|memver_|mem_|skill_|sklfile_|sklscan_|sklver_|sklvfile_|skluse_|file_|sesrsc_|evt_|vol_|stgrant_|staudit_)[^"'`\s]*)["'`]/g
const CANONICAL_CORE_ID_PATTERN =
  /^(?:agent_|sess_|task_|trig_|env_|secret_|vault_|cred_|sbx_|memstore_|memver_|mem_|skill_|sklfile_|sklscan_|sklver_|sklvfile_|skluse_|file_|sesrsc_|evt_|vol_|stgrant_|staudit_)[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/
const ENTITY_PREFIX_ALTERNATION =
  'agent_|sess_|task_|trig_|env_|secret_|vault_|cred_|sbx_|memstore_|memver_|mem_|skill_|sklfile_|sklscan_|sklver_|sklvfile_|skluse_|file_|sesrsc_|evt_|vol_|stgrant_|staudit_'
const REGISTERED_ENTITY_PREFIXES = ENTITY_PREFIX_ALTERNATION.split('|')
const REGISTERED_ENTITY_PREFIX_LENGTHS = new Set(
  REGISTERED_ENTITY_PREFIXES.map((prefix) => prefix.length),
)
const DISPLAY_ID_HELPERS = ['entityIdUuid', 'eventIdTimestamp', 'shortEntityId'] as const
const DISPLAY_ID_HELPER_ALLOWLIST = {
  'app/managed/quickstart/page.tsx': { 'QuickstartPage::shortEntityId': 6 },
  'app/managed/sessions/[sessionId]/page.tsx': { 'SessionDetailPageInner::shortEntityId': 2 },
  'components/managed/session/event-detail.tsx': {
    'EventDetail::shortEntityId': 1,
    'parseEventTime::eventIdTimestamp': 1,
  },
  'components/managed/session/event-row.tsx': { 'parseEventTime::eventIdTimestamp': 1 },
  'components/managed/session/event-timeline.tsx': { 'parseEventTime::eventIdTimestamp': 1 },
  'lib/managed/entity-id-display.ts': {
    'eventIdTimestamp::entityIdUuid': 1,
    'shortEntityId::entityIdUuid': 1,
  },
} as const
const PREFIX_REMOVAL_ALLOWLIST = {
  'lib/managed/entity-id-display.ts': { 'entityIdUuid::prefix_length_slice': 1 },
} as const
const NON_ENTITY_CORE_PREFIX_LITERAL_ALLOWLIST = {} as const

const MANUAL_ENTITY_ID_REMOVAL_PATTERNS = [
  new RegExp(`\\.replace\\(\\s*\\/\\^(?:${ENTITY_PREFIX_ALTERNATION})`, 'g'),
  new RegExp(
    `\\.(?:slice|substring)\\(\\s*(?:ENTITY_ID_PREFIXES(?:\\[[^\\]]+\\]|\\.[A-Za-z]+)|["'](?:${ENTITY_PREFIX_ALTERNATION})["'])\\.length`,
    'g',
  ),
  new RegExp(
    `\\.split\\(\\s*(?:ENTITY_ID_PREFIXES(?:\\[[^\\]]+\\]|\\.[A-Za-z]+)|["'](?:${ENTITY_PREFIX_ALTERNATION})["'])`,
    'g',
  ),
  /\.split\(\s*["']_["']\s*\)\s*\.(?:slice|shift)\b/g,
]

function isAllowedNonEntityCorePrefixLiteral(file: string, value: string): boolean {
  const relativeFile = path.relative(process.cwd(), file)
  const allowedValues = NON_ENTITY_CORE_PREFIX_LITERAL_ALLOWLIST[
    relativeFile as keyof typeof NON_ENTITY_CORE_PREFIX_LITERAL_ALLOWLIST
  ] as readonly string[] | undefined
  return allowedValues?.includes(value) ?? false
}

function collectTestFiles(directory: string): string[] {
  return readdirSync(directory, { withFileTypes: true }).flatMap((entry) => {
    if (entry.name === 'node_modules' || entry.name.startsWith('.')) return []
    const entryPath = path.join(directory, entry.name)
    if (entry.isDirectory()) return collectTestFiles(entryPath)
    return TEST_FILE_PATTERN.test(entry.name) ? [entryPath] : []
  })
}

function collectProductionFiles(directory: string): string[] {
  return readdirSync(directory, { withFileTypes: true }).flatMap((entry) => {
    if (entry.name === 'node_modules' || entry.name.startsWith('.')) return []
    const entryPath = path.join(directory, entry.name)
    if (entry.isDirectory()) return collectProductionFiles(entryPath)
    return SOURCE_FILE_PATTERN.test(entry.name) && !TEST_FILE_PATTERN.test(entry.name)
      ? [entryPath]
      : []
  })
}

function readProjectFile(relativePath: string): string {
  return readFileSync(path.join(process.cwd(), relativePath), 'utf8')
}

function sourceFileFor(source: string, relativePath = 'guard.tsx'): ts.SourceFile {
  return ts.createSourceFile(relativePath, source, ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX)
}

type DisplayIdHelper = (typeof DISPLAY_ID_HELPERS)[number]

interface DisplayHelperBindings {
  helpers: Map<string, DisplayIdHelper>
  namespaces: Set<string>
}

function newDisplayHelperBindings(): DisplayHelperBindings {
  return {
    helpers: new Map(DISPLAY_ID_HELPERS.map((helper) => [helper, helper])),
    namespaces: new Set(),
  }
}

function copyDisplayHelperBindings(bindings: DisplayHelperBindings): DisplayHelperBindings {
  return {
    helpers: new Map(bindings.helpers),
    namespaces: new Set(bindings.namespaces),
  }
}

function resolveDisplayHelper(
  expression: ts.Expression,
  bindings: DisplayHelperBindings,
): DisplayIdHelper | undefined {
  if (ts.isIdentifier(expression)) return bindings.helpers.get(expression.text)
  if (
    ts.isPropertyAccessExpression(expression) &&
    ts.isIdentifier(expression.expression) &&
    bindings.namespaces.has(expression.expression.text) &&
    DISPLAY_ID_HELPERS.includes(expression.name.text as DisplayIdHelper)
  ) {
    return expression.name.text as DisplayIdHelper
  }
  return undefined
}

function isManagedIdModule(node: ts.Expression, relativePath: string): boolean {
  if (!ts.isStringLiteral(node)) return false
  if (node.text === '@/lib/managed/entity-id-display') return true
  if (!node.text.startsWith('.')) return false
  const normalizedFile = relativePath.replaceAll('\\', '/')
  const resolved = path.posix
    .normalize(path.posix.join(path.posix.dirname(normalizedFile), node.text))
    .replace(/\.(?:ts|tsx|js|jsx)$/, '')
  return (
    resolved === 'lib/managed/entity-id-display' ||
    resolved.endsWith('/lib/managed/entity-id-display')
  )
}

function analyzeDisplayHelpers(
  source: string,
  relativePath = 'guard.tsx',
): {
  counts: Record<string, number>
  forbiddenLines: number[]
} {
  const sourceFile = sourceFileFor(source, relativePath)
  const counts: Record<string, number> = {}
  const forbiddenLines = new Set<number>()
  const equalityOperators = new Set([
    ts.SyntaxKind.EqualsEqualsToken,
    ts.SyntaxKind.EqualsEqualsEqualsToken,
    ts.SyntaxKind.ExclamationEqualsToken,
    ts.SyntaxKind.ExclamationEqualsEqualsToken,
  ])
  const forbiddenPropertyNames = new Set(['body', 'payload', 'queryKey', 'cacheKey', 'href'])
  const forbiddenCalls =
    /^(?:apiResource|apiCollection|managed(?:Get|Post|Put|Patch|Delete)|fetch$|setQueryData$|invalidateQueries$|router\.|.*\.(?:request|get|post|put|patch|delete|has|find|findIndex|some|filter)$)/

  const recordCall = (node: ts.CallExpression, helper: DisplayIdHelper, scope: string): void => {
    const key = `${scope}::${helper}`
    counts[key] = (counts[key] ?? 0) + 1
    let ancestor = node.parent
    while (ancestor && !ts.isStatement(ancestor) && !ts.isSourceFile(ancestor)) {
      const forbiddenEquality =
        ts.isBinaryExpression(ancestor) && equalityOperators.has(ancestor.operatorToken.kind)
      const forbiddenCall =
        ts.isCallExpression(ancestor) &&
        ancestor !== node &&
        forbiddenCalls.test(ancestor.expression.getText(sourceFile))
      const forbiddenProperty =
        ts.isPropertyAssignment(ancestor) &&
        forbiddenPropertyNames.has(ancestor.name.getText(sourceFile).replace(/["']/g, ''))
      const forbiddenVariable =
        ts.isVariableDeclaration(ancestor) &&
        forbiddenPropertyNames.has(ancestor.name.getText(sourceFile))
      const forbiddenLookup = ts.isElementAccessExpression(ancestor)
      const forbiddenJsxAttribute =
        ts.isJsxAttribute(ancestor) && ancestor.name.getText(sourceFile) === 'href'
      if (
        forbiddenEquality ||
        forbiddenCall ||
        forbiddenProperty ||
        forbiddenVariable ||
        forbiddenLookup ||
        forbiddenJsxAttribute
      ) {
        forbiddenLines.add(
          sourceFile.getLineAndCharacterOfPosition(node.getStart(sourceFile)).line + 1,
        )
        break
      }
      ancestor = ancestor.parent
    }
  }

  const visit = (node: ts.Node, scope: string, bindings: DisplayHelperBindings): void => {
    if (ts.isImportDeclaration(node) && isManagedIdModule(node.moduleSpecifier, relativePath)) {
      const namedBindings = node.importClause?.namedBindings
      if (namedBindings && ts.isNamedImports(namedBindings)) {
        for (const specifier of namedBindings.elements) {
          const importedName = specifier.propertyName?.text ?? specifier.name.text
          if (DISPLAY_ID_HELPERS.includes(importedName as DisplayIdHelper)) {
            bindings.helpers.set(specifier.name.text, importedName as DisplayIdHelper)
          }
        }
      } else if (namedBindings && ts.isNamespaceImport(namedBindings)) {
        bindings.namespaces.add(namedBindings.name.text)
      }
      return
    }

    if (ts.isFunctionDeclaration(node) && node.body) {
      const childBindings = copyDisplayHelperBindings(bindings)
      for (const parameter of node.parameters) {
        if (ts.isIdentifier(parameter.name)) childBindings.helpers.delete(parameter.name.text)
      }
      for (const statement of node.body.statements) {
        visit(statement, node.name?.text ?? '<anonymous>', childBindings)
      }
      return
    }

    if (
      ts.isVariableDeclaration(node) &&
      ts.isObjectBindingPattern(node.name) &&
      node.initializer &&
      ts.isIdentifier(node.initializer) &&
      bindings.namespaces.has(node.initializer.text)
    ) {
      for (const element of node.name.elements) {
        if (!ts.isIdentifier(element.name)) continue
        const importedName = element.propertyName?.getText(sourceFile) ?? element.name.text
        if (DISPLAY_ID_HELPERS.includes(importedName as DisplayIdHelper)) {
          bindings.helpers.set(element.name.text, importedName as DisplayIdHelper)
        }
      }
      return
    }

    if (ts.isVariableDeclaration(node) && ts.isIdentifier(node.name) && node.initializer) {
      if (ts.isArrowFunction(node.initializer) || ts.isFunctionExpression(node.initializer)) {
        const childBindings = copyDisplayHelperBindings(bindings)
        for (const parameter of node.initializer.parameters) {
          if (ts.isIdentifier(parameter.name)) childBindings.helpers.delete(parameter.name.text)
        }
        visit(node.initializer.body, node.name.text, childBindings)
        return
      }
      visit(node.initializer, scope, bindings)
      const helper = resolveDisplayHelper(node.initializer, bindings)
      bindings.helpers.delete(node.name.text)
      bindings.namespaces.delete(node.name.text)
      if (helper) bindings.helpers.set(node.name.text, helper)
      if (ts.isIdentifier(node.initializer) && bindings.namespaces.has(node.initializer.text)) {
        bindings.namespaces.add(node.name.text)
      }
      return
    }

    if (
      ts.isBinaryExpression(node) &&
      node.operatorToken.kind === ts.SyntaxKind.EqualsToken &&
      ts.isIdentifier(node.left)
    ) {
      visit(node.right, scope, bindings)
      const helper = resolveDisplayHelper(node.right, bindings)
      bindings.helpers.delete(node.left.text)
      bindings.namespaces.delete(node.left.text)
      if (helper) bindings.helpers.set(node.left.text, helper)
      if (ts.isIdentifier(node.right) && bindings.namespaces.has(node.right.text)) {
        bindings.namespaces.add(node.left.text)
      }
      return
    }

    if (ts.isCallExpression(node)) {
      const helper = resolveDisplayHelper(node.expression, bindings)
      if (helper) recordCall(node, helper, scope)
    }
    ts.forEachChild(node, (child) => visit(child, scope, bindings))
  }
  visit(sourceFile, '<module>', newDisplayHelperBindings())
  return {
    counts,
    forbiddenLines: [...forbiddenLines].sort((left, right) => left - right),
  }
}

function displayHelperUsageCounts(source: string, relativePath?: string): Record<string, number> {
  return analyzeDisplayHelpers(source, relativePath).counts
}

function forbiddenDisplayHelperLines(source: string, relativePath?: string): number[] {
  return analyzeDisplayHelpers(source, relativePath).forbiddenLines
}

function staticString(node: ts.Expression): string | undefined {
  if (ts.isStringLiteral(node) || ts.isNoSubstitutionTemplateLiteral(node)) return node.text
  if (ts.isParenthesizedExpression(node)) return staticString(node.expression)
  if (ts.isBinaryExpression(node) && node.operatorToken.kind === ts.SyntaxKind.PlusToken) {
    const left = staticString(node.left)
    const right = staticString(node.right)
    return left === undefined || right === undefined ? undefined : left + right
  }
  if (ts.isTemplateExpression(node)) {
    let value = node.head.text
    for (const span of node.templateSpans) {
      const expression = staticString(span.expression)
      if (expression === undefined) return undefined
      value += expression + span.literal.text
    }
    return value
  }
  return undefined
}

function idLikeExpression(node: ts.Expression): boolean {
  if (
    ts.isParenthesizedExpression(node) ||
    ts.isAsExpression(node) ||
    ts.isTypeAssertionExpression(node) ||
    ts.isNonNullExpression(node)
  ) {
    return idLikeExpression(node.expression)
  }
  if (ts.isIdentifier(node)) return /(?:^id$|Id$|ID$|_id$|^sid$)/.test(node.text)
  if (ts.isPropertyAccessExpression(node)) {
    return /(?:^id$|Id$|ID$|_id$)/.test(node.name.text)
  }
  if (ts.isElementAccessExpression(node) && node.argumentExpression) {
    const key = staticString(node.argumentExpression)
    return key !== undefined && /(?:^id$|Id$|ID$|_id$)/.test(key)
  }
  if (ts.isCallExpression(node)) {
    return /(?:Id|ID)$/.test(node.expression.getText())
  }
  return false
}

function prefixRemovalKind(
  node: ts.CallExpression,
  sourceFile: ts.SourceFile,
  relativePath: string,
): string | undefined {
  const text = node.getText(sourceFile)
  const kinds = [
    'prefix_regex_replace',
    'prefix_length_slice',
    'prefix_split',
    'underscore_split',
  ] as const
  for (const [index, pattern] of MANUAL_ENTITY_ID_REMOVAL_PATTERNS.entries()) {
    pattern.lastIndex = 0
    if (pattern.test(text)) return kinds[index]
  }

  if (!ts.isPropertyAccessExpression(node.expression)) return undefined
  const method = node.expression.name.text
  const replacement = node.arguments[1] ? staticString(node.arguments[1]) : undefined
  if (method === 'replace' && replacement === '' && node.arguments[0]) {
    const directPrefix = staticString(node.arguments[0])
    if (directPrefix && REGISTERED_ENTITY_PREFIXES.includes(directPrefix)) {
      return 'prefix_literal_replace'
    }
    const regexConstructor = node.arguments[0]
    if (
      ts.isNewExpression(regexConstructor) &&
      ts.isIdentifier(regexConstructor.expression) &&
      regexConstructor.expression.text === 'RegExp' &&
      regexConstructor.arguments?.[0]
    ) {
      const pattern = staticString(regexConstructor.arguments[0])
      if (pattern && REGISTERED_ENTITY_PREFIXES.some((prefix) => pattern === `^${prefix}`)) {
        return 'prefix_regexp_constructor_replace'
      }
    }
  }

  if (
    ['slice', 'substring', 'substr'].includes(method) &&
    node.arguments[0] &&
    ts.isNumericLiteral(node.arguments[0]) &&
    REGISTERED_ENTITY_PREFIX_LENGTHS.has(Number(node.arguments[0].text)) &&
    (idLikeExpression(node.expression.expression) ||
      relativePath.replaceAll('\\', '/').endsWith('lib/managed/id.ts'))
  ) {
    return 'prefix_numeric_offset'
  }
  return undefined
}

function analyzePrefixRemovals(
  source: string,
  relativePath = 'guard.tsx',
): {
  counts: Record<string, number>
  lines: number[]
} {
  const sourceFile = sourceFileFor(source, relativePath)
  const counts: Record<string, number> = {}
  const lines = new Set<number>()
  const visit = (node: ts.Node, scope: string): void => {
    if (ts.isFunctionDeclaration(node) && node.body) {
      for (const statement of node.body.statements) {
        visit(statement, node.name?.text ?? '<anonymous>')
      }
      return
    }
    if (
      ts.isVariableDeclaration(node) &&
      ts.isIdentifier(node.name) &&
      node.initializer &&
      (ts.isArrowFunction(node.initializer) || ts.isFunctionExpression(node.initializer))
    ) {
      visit(node.initializer.body, node.name.text)
      return
    }
    if (ts.isCallExpression(node)) {
      const kind = prefixRemovalKind(node, sourceFile, relativePath)
      if (kind) {
        const key = `${scope}::${kind}`
        counts[key] = (counts[key] ?? 0) + 1
        lines.add(sourceFile.getLineAndCharacterOfPosition(node.getStart(sourceFile)).line + 1)
      }
    }
    ts.forEachChild(node, (child) => visit(child, scope))
  }
  visit(sourceFile, '<module>')
  return { counts, lines: [...lines].sort((left, right) => left - right) }
}

function prefixRemovalUsageCounts(source: string, relativePath?: string): Record<string, number> {
  return analyzePrefixRemovals(source, relativePath).counts
}

function manualEntityIdRemovalLines(source: string, relativePath?: string): number[] {
  return analyzePrefixRemovals(source, relativePath).lines
}

function removedHelperLines(source: string): number[] {
  const sourceFile = sourceFileFor(source)
  const lines = new Set<number>()
  const record = (node: ts.Node): void => {
    lines.add(sourceFile.getLineAndCharacterOfPosition(node.getStart(sourceFile)).line + 1)
  }
  const visit = (node: ts.Node): void => {
    if (
      ts.isImportSpecifier(node) &&
      ['stripIdPrefix', 'withIdPrefix'].includes(node.propertyName?.text ?? node.name.text)
    ) {
      record(node)
    } else if (
      ts.isCallExpression(node) &&
      ((ts.isIdentifier(node.expression) &&
        ['stripIdPrefix', 'withIdPrefix'].includes(node.expression.text)) ||
        (ts.isPropertyAccessExpression(node.expression) &&
          ['stripIdPrefix', 'withIdPrefix'].includes(node.expression.name.text)))
    ) {
      record(node)
    }
    ts.forEachChild(node, visit)
  }
  visit(sourceFile)
  return [...lines].sort((left, right) => left - right)
}

describe('typed entity id architecture', () => {
  it('does not import or call legacy prefix helpers in production code', () => {
    const violations = collectProductionFiles(process.cwd()).flatMap((file) =>
      removedHelperLines(readFileSync(file, 'utf8')).map(
        (line) => `${path.relative(process.cwd(), file)}:${line}`,
      ),
    )

    expect(violations).toEqual([])
  })

  it('locks every manual entity-prefix removal node', () => {
    const actual: Record<string, Record<string, number>> = {}
    for (const file of collectProductionFiles(process.cwd())) {
      const relativePath = path.relative(process.cwd(), file)
      const counts = prefixRemovalUsageCounts(readFileSync(file, 'utf8'), relativePath)
      if (Object.keys(counts).length) actual[relativePath] = counts
    }

    expect(actual).toEqual(PREFIX_REMOVAL_ALLOWLIST)
  })

  it('locks display-only entity ID helper call sites and contexts', () => {
    const actual: Record<string, Record<string, number>> = {}
    const forbiddenContexts: string[] = []
    for (const file of collectProductionFiles(process.cwd())) {
      const relativePath = path.relative(process.cwd(), file)
      const source = readFileSync(file, 'utf8')
      const counts = displayHelperUsageCounts(source, relativePath)
      if (Object.keys(counts).length) actual[relativePath] = counts
      forbiddenContexts.push(
        ...forbiddenDisplayHelperLines(source, relativePath).map(
          (line) => `${relativePath}:${line}`,
        ),
      )
    }

    expect(actual).toEqual(DISPLAY_ID_HELPER_ALLOWLIST)
    expect(forbiddenContexts).toEqual([])
  })

  it('detects representative forbidden normalization and helper contexts', () => {
    expect(manualEntityIdRemovalLines("id.replace(/^sess_/, '')")).toEqual([1])
    expect(manualEntityIdRemovalLines('id.slice(ENTITY_ID_PREFIXES.session.length)')).toEqual([1])
    expect(manualEntityIdRemovalLines("id.split('task_')")).toEqual([1])
    expect(manualEntityIdRemovalLines("id.split('_').slice(1).join('_')")).toEqual([1])
    expect(manualEntityIdRemovalLines("id.replace(\n  /^sess_/,\n  '',\n)")).toEqual([1])
    expect(
      forbiddenDisplayHelperLines('const same = shortEntityId(\n  id,\n  kind,\n) === candidate'),
    ).toEqual([1])
    expect(forbiddenDisplayHelperLines('managedGet(\n  shortEntityId(id, kind),\n)')).toEqual([2])
    expect(forbiddenDisplayHelperLines('const cacheKey = shortEntityId(id, kind)')).toEqual([1])
    expect(
      removedHelperLines("import { stripIdPrefix as strip } from './id'\nstrip(value)"),
    ).toEqual([1])
    expect(forbiddenDisplayHelperLines("const label = shortEntityId(id, 'agent')")).toEqual([])
  })

  it('resolves display helper import and local aliases semantically', () => {
    const source = `
import { shortEntityId as short } from '@/lib/managed/entity-id-display'
import * as entityIds from '@/lib/managed/entity-id-display'

function probe(id, candidate) {
  const localShort = short
  const localUuid = entityIds.entityIdUuid
  const label = localShort(id, 'agent')
  return localUuid(id, 'agent') === candidate
}
`

    expect(displayHelperUsageCounts(source)).toEqual({
      'probe::shortEntityId': 1,
      'probe::entityIdUuid': 1,
    })
    expect(forbiddenDisplayHelperLines(source)).toEqual([9])
  })

  it('resolves relative named, namespace, and destructured helper aliases', () => {
    const source = `
import { shortEntityId as short } from './entity-id-display'
import * as ids from '../managed/entity-id-display'

const { entityIdUuid: raw, shortEntityId: destructuredShort } = ids
const rawAlias = raw

function probe(id, candidate) {
  const label = short(id, 'agent')
  const secondLabel = destructuredShort(id, 'agent')
  return rawAlias(id, 'agent') === candidate
}
`

    expect(displayHelperUsageCounts(source, 'lib/managed/fixture.ts')).toEqual({
      'probe::shortEntityId': 2,
      'probe::entityIdUuid': 1,
    })
    expect(forbiddenDisplayHelperLines(source, 'lib/managed/fixture.ts')).toEqual([11])
  })

  it('classifies every prefix strip inside the helper module', () => {
    const source = `
function entityIdUuid(id, kind) {
  return id.slice(ENTITY_ID_PREFIXES[kind].length)
}
function newStripHelper(id) {
  return id.replace(/^sess_/, '')
}
`

    expect(prefixRemovalUsageCounts(source)).toEqual({
      'entityIdUuid::prefix_length_slice': 1,
      'newStripHelper::prefix_regex_replace': 1,
    })
  })

  it('detects literal, RegExp-constructor, and numeric-offset prefix stripping', () => {
    const source = `
function direct(sessionId) {
  return sessionId.replace('sess_', '')
}
function constructed(sessionId) {
  return sessionId.replace(new RegExp('^sess_'), '')
}
function numeric(sessionId) {
  return sessionId.substring(5)
}
`

    expect(prefixRemovalUsageCounts(source)).toEqual({
      'direct::prefix_literal_replace': 1,
      'constructed::prefix_regexp_constructor_replace': 1,
      'numeric::prefix_numeric_offset': 1,
    })
  })

  it('keeps core entity fixtures canonical', () => {
    const violations: string[] = []
    for (const file of collectTestFiles(process.cwd())) {
      if (file.endsWith('entity-id.test.ts') || file.endsWith('entity-id-architecture.test.ts')) {
        continue
      }
      const source = readFileSync(file, 'utf8')
      for (const match of source.matchAll(QUOTED_CORE_ID_PATTERN)) {
        if (
          match[1].includes('${') ||
          match[1].startsWith('agent_toolset_') ||
          ['secret_ref', 'secret_key', 'secret_data'].includes(match[1]) ||
          (match[1] === 'secret_refs' && file.endsWith('environment-response-parsers.test.ts')) ||
          isAllowedNonEntityCorePrefixLiteral(file, match[1])
        )
          continue
        if (!CANONICAL_CORE_ID_PATTERN.test(match[1])) {
          violations.push(`${path.relative(process.cwd(), file)}: ${match[1]}`)
        }
      }
    }

    expect(violations).toEqual([])
  })

  it('parses route and stream ids at the frontend boundary', () => {
    expect(readProjectFile('lib/managed/sse.ts')).toContain('sessionId: SessionId | null')
    expect(readProjectFile('app/managed/agents/[agentId]/page.tsx')).toContain(
      'parseAgentId(rawAgentId)',
    )
    expect(readProjectFile('app/managed/agents/[agentId]/edit/page.tsx')).toContain(
      'parseAgentId(rawAgentId)',
    )
    expect(readProjectFile('app/managed/sessions/[sessionId]/page.tsx')).toContain(
      'parseSessionId(rawSessionId)',
    )
    expect(readProjectFile('app/managed/triggers/[triggerId]/page.tsx')).toContain(
      'parseTriggerId(rawId)',
    )
    expect(readProjectFile('app/managed/environments/[envId]/page.tsx')).toContain(
      'parseEnvironmentId(rawId)',
    )
  })

  it('does not strip canonical session ids in quickstart runtime flows', () => {
    const source = readProjectFile('app/managed/quickstart/page.tsx')

    expect(source).toContain('parseSessionId(rawSessionId)')
    expect(source).not.toContain('stripIdPrefix(currentSession.id)')
  })

  it('runtime-validates Agent and Session responses at every core ingress', () => {
    const agentParsers = readProjectFile('lib/managed/agent-response-parsers.ts')
    const sessionParsers = readProjectFile('lib/managed/session-response-parsers.ts')
    const agentList = readProjectFile('app/managed/agents/page.tsx')
    const agentDetail = readProjectFile('app/managed/agents/[agentId]/page.tsx')
    const sessionList = readProjectFile('app/managed/sessions/page.tsx')
    const sessionDetail = readProjectFile('app/managed/sessions/[sessionId]/page.tsx')

    expect(agentParsers).toContain('id: parseAgentId(raw.id)')
    expect(agentParsers).toContain('skill_id: parseSkillId(skill.skill_id)')
    expect(sessionParsers).toContain('id: parseSessionId(raw.id)')
    expect(sessionParsers).toContain(
      'credential_group_ids: raw.credential_group_ids?.map(parseCredentialGroupId)',
    )
    expect(agentList).toContain('parseItem: parseAgentResponse')
    expect(agentDetail).toContain('.then(parseAgentResponse)')
    expect(sessionList).toContain('parseItem: parseSessionResponse')
    expect(sessionDetail).toContain('.then(parseSessionResponse)')
  })

  it('runtime-validates analytics response ids before branding them', () => {
    const hooks = readProjectFile('lib/managed/analytics/hooks.ts')
    const parsers = readProjectFile('lib/managed/analytics/response-parsers.ts')

    expect(hooks).toContain('parseCallsListResponse')
    expect(hooks).toContain('parseAgentMetricsResponse')
    expect(hooks).toContain('parseHealthCheckResponse')
    expect(hooks).toContain('parseAgentRankingResponse')
    expect(parsers).toContain('id: parseTaskId(record.id)')
    expect(parsers).toContain('session_id: parseNullableId<SessionId>')
    expect(parsers).toContain('agent_id: parseNullableId<AgentId>')
  })

  it('keeps trigger hooks and response data typed end-to-end', () => {
    const hooks = readProjectFile('lib/managed/triggers.ts')
    const parsers = readProjectFile('lib/managed/trigger-response-parsers.ts')

    expect(hooks).toContain('useTestFireWebhook(triggerId: TriggerId)')
    expect(hooks).toContain('useWebhookSample(triggerId: TriggerId | undefined')
    expect(hooks).toContain('parseItem: parseTriggerRunResponse')
    expect(hooks).not.toMatch(/triggerId:\s*string/)
    expect(parsers).toContain('id: parseTriggerId(response.id)')
    expect(parsers).toContain('trigger_id: parseNullableId<TriggerId>')
    expect(parsers).toContain('id: parseTaskId(raw.id)')
  })

  it('keeps environment routes and response data typed end-to-end', () => {
    const listPage = readProjectFile('app/managed/environments/page.tsx')
    const parsers = readProjectFile('lib/managed/environment-response-parsers.ts')
    const storageParsers = readProjectFile('lib/managed/storage-mount-response-parsers.ts')

    expect(listPage).toContain('parseItem: parseEnvironmentResponse')
    expect(parsers).toContain('id: parseEnvironmentId(raw.id)')
    expect(parsers).toContain('parseStorageVolumeId(volume.volume_id)')
    expect(readProjectFile('lib/managed/api-paths.ts')).toContain('parseAnyEntityId')
    expect(storageParsers).toContain('environment_id: parseOptionalId<EnvironmentId>')
  })

  it('keeps API resource helper ID parameters branded', () => {
    const apiPaths = readProjectFile('lib/managed/api-paths.ts')
    const apiResourceId = apiPaths.match(
      /export function apiResourceId\([^)]*\)[^{]*\{(?<body>[\s\S]*?)\n\}/,
    )

    expect(apiPaths).toContain('apiResourceId(id: AnyEntityId)')
    expect(apiPaths).toMatch(/apiResourcePath\(\s*resource: string,\s*id: AnyEntityId,/)
    expect(apiPaths).toMatch(/apiResourceSubpath\(\s*resource: string,\s*id: AnyEntityId,/)
    expect(apiResourceId?.groups?.body).toContain('return parseAnyEntityId(id)')
    expect(apiResourceId?.groups?.body).not.toMatch(
      /\.replace\(|\b(?:stripIdPrefix|withIdPrefix|removeprefix)\b/,
    )
  })

  it('builds collection sentinels as explicit static paths', () => {
    const sessionPage = readProjectFile('app/managed/sessions/[sessionId]/page.tsx')
    const skillsPage = readProjectFile('app/managed/skills/page.tsx')

    expect(sessionPage).toContain('`/network-policies/sessions/${encodeURIComponent(id)}`')
    expect(sessionPage).not.toContain("apiResourceSubpath('network-policies', 'sessions'")
    expect(skillsPage).toContain("apiCollectionPath('skills/usage/search'")
    expect(skillsPage).not.toContain("apiResourceSubpath('skills', 'usage'")
  })

  it('parses storage identities at every frontend ingress', () => {
    const types = readProjectFile('types/managed.ts')
    const parsers = readProjectFile('lib/managed/storage-mount-response-parsers.ts')
    const sessionParsers = readProjectFile('lib/managed/session-response-parsers.ts')
    const page = readProjectFile('components/managed/storage-volumes/storage-volumes-page.tsx')

    expect(types).toContain('id: StorageVolumeId')
    expect(types).toContain('id: StorageGrantId')
    expect(types).toContain('id: StorageMountAuditId')
    expect(types).toContain('volume_id: StorageVolumeId')
    expect(types).toContain('id: SessionResourceId')
    expect(parsers).toContain('id: parseStorageVolumeId(raw.id)')
    expect(parsers).toContain('id: parseStorageGrantId(raw.id)')
    expect(parsers).toContain('id: parseStorageMountAuditId(raw.id)')
    expect(parsers).toContain('id: parseSessionResourceId(raw.id)')
    expect(sessionParsers).toContain('storage_mounts: raw.storage_mounts?.map')
    expect(page).toContain('managedGet<unknown>')
    expect(page).toContain('.then(parseStorageVolumeListResponse)')
    expect(page).toContain('.then(parseStorageVolumeResponse)')
    expect(page).toContain('.then(parseStorageProjectGrantResponse)')
    expect(page).toContain('.then(parseStorageOrganizationGrantResponse)')
    expect(page).toContain('apiResourceId(selectedVolume.id)')
    expect(page).toContain('parseCursor: parseStorageMountAuditId')
    expect(readProjectFile('hooks/managed/use-paginated-list.ts')).not.toContain('apiResourceId')
  })

  it('validates typed entity list cursors with their concrete parsers', () => {
    const typedLists = [
      ['app/managed/agents/page.tsx', 'parseCursor: parseAgentId'],
      ['app/managed/sessions/page.tsx', 'parseCursor: parseSessionId'],
      ['app/managed/environments/page.tsx', 'parseCursor: parseEnvironmentId'],
      ['app/managed/environments/page.tsx', 'parseCursor: parseCredentialId'],
      ['app/managed/environments/[envId]/page.tsx', 'parseCursor: parseCredentialId'],
      [
        'components/managed/credentials/model-connection-list.tsx',
        'parseCursor: parseCredentialId',
      ],
      ['app/managed/memory-stores/page.tsx', 'parseCursor: parseMemoryStoreId'],
      ['app/managed/skills/page.tsx', 'parseCursor: parseSkillId'],
      ['app/managed/files/page.tsx', 'parseCursor: parseFileId'],
      ['app/managed/api-keys/page.tsx', 'parseCursor: parseApiKeyId'],
      [
        'components/managed/credentials/mcp-credential-group-list.tsx',
        'parseCursor: parseCredentialGroupId',
      ],
      ['lib/managed/triggers.ts', 'parseCursor: parseTaskId'],
      [
        'components/managed/storage-volumes/storage-volumes-page.tsx',
        'parseCursor: parseStorageMountAuditId',
      ],
    ] as const

    for (const [file, parser] of typedLists) {
      expect(readProjectFile(file), `${file} must use ${parser}`).toContain(parser)
    }

    const nonEntityLists = [
      'app/managed/settings/organizations/[organizationId]/members/page.tsx',
      'app/managed/platform/users/page.tsx',
      'app/managed/projects/page.tsx',
      'app/managed/projects/[projectId]/members/page.tsx',
      'app/managed/settings/page.tsx',
    ]

    for (const file of nonEntityLists) {
      expect(readProjectFile(file), `${file} must preserve opaque cursors`).not.toContain(
        'parseCursor:',
      )
    }
  })

  it('keeps credential routes and response data typed end-to-end', () => {
    const listPage = readProjectFile('components/managed/credentials/model-connection-list.tsx')
    const detailPage = readProjectFile('app/managed/credentials/[credentialId]/page.tsx')
    const detailComponent = readProjectFile('components/managed/credentials/credential-detail.tsx')
    const parsers = readProjectFile('lib/managed/credential-response-parsers.ts')

    expect(listPage).toContain('parseItem: parseCredentialResponse')
    expect(detailPage).toContain('parseCredentialId(credentialId)')
    expect(detailComponent).toContain('parseCredentialDetailResponse(res)')
    expect(parsers).toContain('id: parseCredentialId(raw.id)')
    expect(readProjectFile('lib/managed/api-paths.ts')).toContain('parseAnyEntityId')
  })

  it('keeps credential-group and credential routes typed end-to-end', () => {
    const listPage = readProjectFile('components/managed/credentials/mcp-credential-group-list.tsx')
    const detailPage = readProjectFile('app/managed/credentials/mcp/[credentialGroupId]/page.tsx')
    const detailComponent = readProjectFile(
      'components/managed/credentials/mcp-credential-group-detail.tsx',
    )
    const parsers = readProjectFile('lib/managed/credential-group-response-parsers.ts')
    const managedTypes = readProjectFile('types/managed.ts')

    expect(listPage).toContain('parseItem: parseCredentialGroupResponse')
    expect(detailPage).toContain('parseCredentialGroupId(credentialGroupId)')
    expect(detailComponent).toContain('parseCredentialGroupCredentialListResponse(response.data)')
    expect(parsers).toContain('parseCredentialResponse(response)')
    expect(parsers).toContain("credential.kind !== 'mcp'")
    expect(parsers).not.toContain('RawCredentialGroupCredential')
    expect(managedTypes).toContain('export interface CredentialGroup')
    expect(managedTypes).toContain('export interface CredentialGroupCredential')
    expect(managedTypes).not.toContain('export interface Vault')
    expect(listPage).not.toContain('vault-response-parsers')
    expect(detailComponent).not.toContain('vault-response-parsers')
    expect(readProjectFile('lib/managed/api-paths.ts')).toContain('parseAnyEntityId')
  })

  it('keeps active environment types canonical while legacy keys stay decoder-only', () => {
    const managedTypes = readProjectFile('types/managed.ts')
    const editor = readProjectFile('components/managed/environments-egress-editor.tsx')
    const parser = readProjectFile('lib/managed/environment-response-parsers.ts')
    const parserTest = readProjectFile('lib/managed/environment-response-parsers.test.ts')

    expect(managedTypes).toContain('environment_credential_ids?: CredentialId[]')
    expect(managedTypes).toContain('credential_field?: string')
    expect(managedTypes).not.toContain('secret_refs?: CredentialId[]')
    expect(managedTypes).not.toContain('secret_key?: string')
    expect(editor).not.toContain('.secret_key')
    expect(parser).not.toContain('backend/contracts/credential_reference_contract.json')
    expect(parserTest).toContain('backend/contracts/credential_reference_contract.json')
  })

  it('keeps sandbox diagnostics typed at the API boundary', () => {
    const page = readProjectFile('app/managed/platform/network-policies/page.tsx')
    const parsers = readProjectFile('lib/managed/network-policy-response-parsers.ts')

    expect(readProjectFile('types/managed.ts')).toContain('sandbox_id: SandboxId')
    expect(page).toContain('managedGet<unknown>')
    expect(page).toContain('.then(parseNetworkPolicyListResponse)')
    expect(parsers).toContain('sandbox_id: parseSandboxId(raw.sandbox_id)')
    expect(parsers).toContain('session_id: parseOptionalId<SessionId>')
    expect(parsers).toContain('task_id: parseOptionalId<TaskId>')
  })

  it('keeps memory resources typed at API boundaries', () => {
    const listPage = readProjectFile('app/managed/memory-stores/page.tsx')
    const detailPage = readProjectFile('app/managed/memory-stores/[storeId]/page.tsx')
    const parsers = readProjectFile('lib/managed/memory-response-parsers.ts')

    expect(listPage).toContain('parseItem: parseMemoryStoreResponse')
    expect(detailPage).toContain('parseMemoryStoreId(rawId ||')
    expect(detailPage).toContain('.then(parseMemoryListResponse)')
    expect(parsers).toContain('id: parseMemoryId(raw.id)')
    expect(parsers).toContain('memory_store_id: parseMemoryStoreId(raw.memory_store_id)')
  })

  it('keeps the complete Skill identity chain typed at API boundaries', () => {
    const page = readProjectFile('app/managed/skills/page.tsx')
    const detailPage = readProjectFile('app/managed/skills/[skillId]/page.tsx')
    const authoring = readProjectFile('hooks/managed/use-skill-authoring.ts')
    const lifecycle = readProjectFile('components/managed/skills/skill-lifecycle-actions.tsx')
    const parsers = readProjectFile('lib/managed/skill-response-parsers.ts')

    expect(page).toContain('parseItem: parseSkillResponse')
    expect(page).toContain('parseSkillVersionFileListResponse(res)')
    expect(page).toContain('parseSkillUsageListResponse(res)')
    expect(detailPage).toContain('parseSkillId(rawSkillId)')
    expect(authoring).toContain('parseSkillAuthoringSaveResponse(')
    expect(authoring).toContain('parseSkillSecurityScanResponse(')
    expect(lifecycle).toContain('parseSkillLifecycleTransitionResponse(')
    expect(authoring).not.toMatch(/draftSkillId:\s*string/)
    expect(parsers).toContain('id: parseSkillFileId(raw.id)')
    expect(parsers).toContain('id: parseSkillVersionFileId(raw.id)')
    expect(parsers).toContain('id: parseSkillUsageId(raw.id)')
  })

  it('keeps file and session-resource identities typed at API boundaries', () => {
    const filesPage = readProjectFile('app/managed/files/page.tsx')
    const sessionPage = readProjectFile('app/managed/sessions/[sessionId]/page.tsx')
    const createDialog = readProjectFile(
      'app/managed/sessions/components/create-session-dialog.tsx',
    )
    const parsers = readProjectFile('lib/managed/file-response-parsers.ts')
    const apiPaths = readProjectFile('lib/managed/api-paths.ts')

    expect(readProjectFile('types/managed.ts')).toContain('id: FileId')
    expect(readProjectFile('types/managed.ts')).toContain('id: SessionResourceId')
    expect(filesPage).toContain('parseItem: parseFileResponse')
    expect(filesPage).toContain("apiResourcePath('files', file.id)")
    expect(createDialog).toContain('parseFileListResponse(response.data)')
    expect(sessionPage).toContain('parseSessionResourceListResponse(response.data)')
    expect(parsers).toContain('id: parseFileId(raw.id)')
    expect(parsers).toContain('id: parseSessionResourceId(raw.id)')
    expect(apiPaths).toContain('parseAnyEntityId')
  })

  it('keeps persisted event identities typed across REST and SSE boundaries', () => {
    const page = readProjectFile('app/managed/sessions/[sessionId]/page.tsx')
    const sse = readProjectFile('lib/managed/sse.ts')
    const parsers = readProjectFile('lib/managed/event-response-parsers.ts')
    const eventHelpers = readProjectFile('lib/managed/session-events.ts')

    expect(readProjectFile('types/managed.ts')).toContain('id?: EventId')
    expect(page).toContain('parseSessionEventListResponse(')
    expect(sse).toContain('parseSessionEventResponse(parsed)')
    expect(parsers).toContain('id: raw.id ? parseEventId(raw.id) : undefined')
    expect(eventHelpers).not.toContain('replace(/^evt_/')
  })
})
