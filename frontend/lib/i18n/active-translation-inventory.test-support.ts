import { readdirSync, statSync } from 'node:fs'
import path from 'node:path'

import ts from 'typescript'

import {
  ALERT_DETAIL_KEYS,
  SUGGESTION_MESSAGE_KEYS,
} from '@/lib/managed/analytics/health-presenter'
import { CRON_PRESETS } from '@/lib/managed/cron'

type CatalogRoot = Record<string, unknown>

type FiniteFamilyName =
  | 'skillEligibility'
  | 'skillSeverity'
  | 'quickstartInput'
  | 'skillStatus'
  | 'cronPresets'
  | 'status'
  | 'alerts'
  | 'suggestions'

export interface ActiveTranslationInventory {
  sourceFileCount: number
  sourceFiles: string[]
  directLeaves: Set<string>
  templateDynamicLeaves: Set<string>
  finiteFamilies: Record<FiniteFamilyName, Set<string>>
  finiteFamilyAdditions: Record<FiniteFamilyName, number>
  activeLeaves: Set<string>
  missingEnglishLeaves: string[]
  missingChineseLeaves: string[]
  counts: {
    direct: number
    dynamic: number
    total: number
  }
}

const excludedSourcePath =
  /(?:^|\/)(?:__fixtures__|__generated__|fixtures|generated|locales)(?:\/|$)/
const excludedSourceFile =
  /(?:\.(?:fixture|spec|stories?|test)|(?:^|[.-])test-support|(?:^|[.-])test-utils|\.generated)\.[cm]?tsx?$/
const declarationFile = /\.d\.[cm]?ts$/
const sourceFilePattern = /\.[cm]?tsx?$/

const skillEligibilityLeaves = [
  ...[
    'skillNotApproved',
    'securityNotScanned',
    'securityScanning',
    'securityFailed',
    'securityBlocked',
    'noSecurityScanHash',
    'contentChangedAfterScan',
    'noPublishedVersion',
    'runtimeNotReady',
    'unknown',
  ].flatMap((slug) => [
    `managed.skills.eligibility.title.${slug}`,
    `managed.skills.eligibility.short.${slug}`,
  ]),
  ...[
    'submit_or_approve',
    'run_security_scan',
    'fix_and_rescan',
    'wait_for_scan',
    'review_skill',
    'none',
  ].map((slug) => `managed.skills.eligibility.action.${slug}`),
]

const fixedFiniteFamilies = {
  skillEligibility: skillEligibilityLeaves,
  skillSeverity: ['critical', 'high', 'medium', 'low', 'info', 'unknown'].map(
    (slug) => `managed.skills.severityLabel.${slug}`,
  ),
  quickstartInput: [
    'managed.quickstart.selectEngineFirst',
    'managed.quickstart.chooseSecret',
    'managed.quickstart.noApiKey',
    'managed.quickstart.noCompatibleSecret',
    'managed.quickstart.agentProcessing',
    'managed.quickstart.waitingForResponse',
    'managed.quickstart.describeAgent',
    'managed.quickstart.reply',
  ],
  skillStatus: [
    'managed.skills.lifecycle.draft',
    'managed.skills.lifecycle.pendingReview',
    'managed.skills.lifecycle.approved',
    'managed.skills.lifecycle.rejected',
    'managed.skills.lifecycle.archived',
    'managed.skills.visibility.project',
    'managed.skills.visibility.organization',
    'managed.skills.visibility.public',
  ],
  cronPresets: CRON_PRESETS.map((preset) => preset.labelKey),
}

function flattenCatalogLeaves(root: unknown, prefix = ''): string[] {
  if (typeof root !== 'object' || root === null || Array.isArray(root)) {
    return prefix ? [prefix] : []
  }
  return Object.entries(root).flatMap(([key, value]) =>
    flattenCatalogLeaves(value, prefix ? `${prefix}.${key}` : key),
  )
}

function catalogContainsRequiredKey(catalogLeaves: Set<string>, key: string): boolean {
  return (
    catalogLeaves.has(key) || (catalogLeaves.has(`${key}_one`) && catalogLeaves.has(`${key}_other`))
  )
}

function collectProductionSourceFiles(frontendRoot: string, directory: string): string[] {
  return readdirSync(directory)
    .sort()
    .flatMap((entry) => {
      const absolutePath = path.join(directory, entry)
      const relativePath = path.relative(frontendRoot, absolutePath).split(path.sep).join('/')
      if (excludedSourcePath.test(relativePath)) return []
      if (statSync(absolutePath).isDirectory()) {
        return collectProductionSourceFiles(frontendRoot, absolutePath)
      }
      if (
        !sourceFilePattern.test(entry) ||
        declarationFile.test(entry) ||
        excludedSourceFile.test(entry)
      )
        return []
      return [absolutePath]
    })
}

function literalTypeValues(type: ts.Type): string[] {
  if (type.isUnion()) return type.types.flatMap(literalTypeValues)
  return type.isStringLiteral() ? [type.value] : []
}

function escapeRegExp(value: string): string {
  return value.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
}

function templatePattern(node: ts.TemplateExpression): RegExp {
  const pattern = [node.head.text, ...node.templateSpans.map((span) => span.literal.text)]
    .map(escapeRegExp)
    .join('[^.]+')
  return new RegExp(`^${pattern}$`)
}

function expandTypedTemplate(
  node: ts.TemplateExpression,
  checker: ts.TypeChecker,
): string[] | null {
  let values = [node.head.text]
  for (const span of node.templateSpans) {
    const expressionValues = literalTypeValues(checker.getTypeAtLocation(span.expression))
    if (expressionValues.length === 0) return null
    values = values.flatMap((prefix) =>
      expressionValues.map((value) => `${prefix}${value}${span.literal.text}`),
    )
  }
  return values
}

function collectObjectStringValues(
  program: ts.Program,
  sourcePath: string,
  variableName: string,
): string[] {
  const sourceFile = program.getSourceFile(sourcePath)
  if (!sourceFile) throw new Error(`TypeScript program did not load ${sourcePath}`)
  const values: string[] = []

  function visit(node: ts.Node) {
    if (
      ts.isVariableDeclaration(node) &&
      ts.isIdentifier(node.name) &&
      node.name.text === variableName &&
      node.initializer &&
      ts.isObjectLiteralExpression(node.initializer)
    ) {
      for (const property of node.initializer.properties) {
        if (
          ts.isPropertyAssignment(property) &&
          (ts.isStringLiteral(property.initializer) ||
            ts.isNoSubstitutionTemplateLiteral(property.initializer))
        ) {
          values.push(property.initializer.text)
        }
      }
    }
    ts.forEachChild(node, visit)
  }

  visit(sourceFile)
  if (values.length === 0) throw new Error(`${variableName} has no string values in ${sourcePath}`)
  return values
}

function isTranslationCall(node: ts.CallExpression): boolean {
  const callee = node.expression
  if (ts.isIdentifier(callee)) return callee.text === 't' || callee.text === 'tr'
  if (!ts.isPropertyAccessExpression(callee) || callee.name.text !== 't') return false
  const owner = callee.expression.getText()
  return /(?:^|\.)(?:i18n|translation|translator)$/.test(owner)
}

export function buildActiveTranslationInventory(
  englishCatalog: CatalogRoot,
  chineseCatalog: CatalogRoot,
): ActiveTranslationInventory {
  const frontendRoot = path.resolve(process.cwd())
  const sourceRoots = ['app', 'components', 'hooks', 'lib'].map((directory) =>
    path.join(frontendRoot, directory),
  )
  const sourceFiles = sourceRoots.flatMap((root) =>
    collectProductionSourceFiles(frontendRoot, root),
  )
  const relativeSourceFiles = sourceFiles.map((file) =>
    path.relative(frontendRoot, file).split(path.sep).join('/'),
  )
  const englishLeaves = new Set(flattenCatalogLeaves(englishCatalog))
  const chineseLeaves = new Set(flattenCatalogLeaves(chineseCatalog))
  const catalogLeaves = new Set([...englishLeaves, ...chineseLeaves])

  const configPath = ts.findConfigFile(frontendRoot, ts.sys.fileExists, 'tsconfig.json')
  if (!configPath) throw new Error('frontend tsconfig.json not found')
  const config = ts.readConfigFile(configPath, ts.sys.readFile)
  const parsedConfig = ts.parseJsonConfigFileContent(config.config, ts.sys, frontendRoot)
  const program = ts.createProgram(parsedConfig.fileNames, parsedConfig.options)
  const checker = program.getTypeChecker()
  const directLeaves = new Set<string>()
  const templateDynamicLeaves = new Set<string>()

  for (const file of sourceFiles) {
    const sourceFile = program.getSourceFile(file)
    if (!sourceFile) throw new Error(`TypeScript program did not load ${file}`)

    function visit(node: ts.Node) {
      if (
        (ts.isStringLiteral(node) || ts.isNoSubstitutionTemplateLiteral(node)) &&
        catalogLeaves.has(node.text)
      ) {
        templateDynamicLeaves.add(node.text)
      }

      if (ts.isCallExpression(node) && node.arguments.length > 0 && isTranslationCall(node)) {
        const key = node.arguments[0]
        if (ts.isStringLiteral(key) || ts.isNoSubstitutionTemplateLiteral(key)) {
          directLeaves.add(key.text)
        } else if (ts.isTemplateExpression(key)) {
          const typedCandidates = expandTypedTemplate(key, checker)
          const candidates =
            typedCandidates ?? [...catalogLeaves].filter((leaf) => templatePattern(key).test(leaf))
          for (const candidate of candidates) {
            templateDynamicLeaves.add(candidate)
          }
        }
      }
      ts.forEachChild(node, visit)
    }

    visit(sourceFile)
  }

  const finiteFamilies: Record<FiniteFamilyName, readonly string[]> = {
    ...fixedFiniteFamilies,
    status: collectObjectStringValues(
      program,
      path.join(frontendRoot, 'lib/managed/status-tone.ts'),
      'STATUS_LABEL_KEY',
    ),
    alerts: ALERT_DETAIL_KEYS,
    suggestions: SUGGESTION_MESSAGE_KEYS,
  }
  const familySets = Object.fromEntries(
    Object.entries(finiteFamilies).map(([name, leaves]) => [name, new Set(leaves)]),
  ) as Record<FiniteFamilyName, Set<string>>
  const activeLeaves = new Set([...directLeaves, ...templateDynamicLeaves])
  const finiteFamilyAdditions = {} as Record<FiniteFamilyName, number>
  for (const [name, leaves] of Object.entries(familySets) as [FiniteFamilyName, Set<string>][]) {
    let additions = 0
    for (const leaf of leaves) {
      if (!activeLeaves.has(leaf)) additions += 1
      activeLeaves.add(leaf)
    }
    finiteFamilyAdditions[name] = additions
  }

  return {
    sourceFileCount: sourceFiles.length,
    sourceFiles: relativeSourceFiles,
    directLeaves,
    templateDynamicLeaves,
    finiteFamilies: familySets,
    finiteFamilyAdditions,
    activeLeaves,
    missingEnglishLeaves: [...activeLeaves]
      .filter((leaf) => !catalogContainsRequiredKey(englishLeaves, leaf))
      .sort(),
    missingChineseLeaves: [...activeLeaves]
      .filter((leaf) => !catalogContainsRequiredKey(chineseLeaves, leaf))
      .sort(),
    counts: {
      direct: directLeaves.size,
      dynamic: activeLeaves.size - directLeaves.size,
      total: activeLeaves.size,
    },
  }
}
