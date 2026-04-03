import nextCoreWebVitals from 'eslint-config-next/core-web-vitals'
import nextTypescript from 'eslint-config-next/typescript'

const eslintConfig = [
  ...nextCoreWebVitals,
  ...nextTypescript,
  {
    rules: {
      // Warn on console.log usage (should use Logger instead)
      'no-console': ['warn', { allow: ['warn', 'error'] }],

      // TypeScript specific rules
      '@typescript-eslint/no-unused-vars': ['warn', { argsIgnorePattern: '^_' }],
      '@typescript-eslint/no-explicit-any': 'warn',
      '@typescript-eslint/no-require-imports': 'warn',
      '@typescript-eslint/ban-ts-comment': ['warn', { minimumDescriptionLength: 0 }],

      // React rules
      'react-hooks/rules-of-hooks': 'error',
      'react-hooks/exhaustive-deps': 'warn',
      // Avoid cascading render; defer setState to next tick (fix in code preferred)
      'react-hooks/set-state-in-effect': 'warn',
      'react-hooks/unsupported-syntax': 'warn',
      'react-hooks/preserve-manual-memoization': 'warn',
      'react-hooks/immutability': 'warn',
      'react-hooks/purity': 'warn',
      'react/no-unescaped-entities': 'warn',
      'prefer-const': 'warn',

      // Enforce function declarations for components (no React.FC)
      // Forbid direct crypto.randomUUID() — use generateUUID() from @/lib/utils/uuid
      'no-restricted-syntax': [
        'error',
        {
          selector: 'TSTypeReference[typeName.right.name="FC"]',
          message: 'Use function declarations instead of React.FC.',
        },
        {
          selector: 'CallExpression[callee.object.name="crypto"][callee.property.name="randomUUID"]',
          message: 'Use generateUUID() from @/lib/utils/uuid instead of crypto.randomUUID() — it includes a fallback for Edge Runtime.',
        },
      ],

      // Enforce unified import paths
      'no-restricted-imports': [
        'error',
        {
          paths: [
            {
              name: 'react-i18next',
              message: 'Use @/lib/i18n instead.',
            },
          ],
          patterns: [
            {
              group: ['@/lib/core/utils/cn'],
              message: 'Use @/lib/utils instead.',
            },
          ],
        },
      ],

      // Import ordering
      'import/order': [
        'warn',
        {
          groups: ['builtin', 'external', 'internal', 'parent', 'sibling', 'index'],
          'newlines-between': 'always',
          alphabetize: { order: 'asc', caseInsensitive: true },
        },
      ],
    },
  },
  // Allow direct react-i18next imports in the i18n infrastructure files
  {
    files: ['lib/i18n/**'],
    rules: {
      'no-restricted-imports': 'off',
    },
  },
]

export default eslintConfig
