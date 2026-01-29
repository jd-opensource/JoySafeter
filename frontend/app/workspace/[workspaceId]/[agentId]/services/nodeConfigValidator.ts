/**
 * Node Configuration Validator - Unified validation using JSON schema.
 *
 * Provides client-side validation using the same rules as the backend
 * to ensure consistency between frontend and backend validation.
 */

export interface ValidationError {
  field: string
  message: string
  severity?: 'error' | 'warning' | 'info'
}

// Custom validation rule types
interface CustomValidationRule {
  name: string
  condition: any
  errorMessage: string
}

interface SimpleCustomValidation {
  message: string
  condition: string
}

interface RulesBasedCustomValidation {
  rules: CustomValidationRule[]
}

type CustomValidation = SimpleCustomValidation | RulesBasedCustomValidation

// Type guard functions
function hasRules(customValidation: CustomValidation): customValidation is RulesBasedCustomValidation {
  return 'rules' in customValidation && Array.isArray(customValidation.rules)
}

function hasCondition(customValidation: CustomValidation): customValidation is SimpleCustomValidation {
  return 'condition' in customValidation && typeof customValidation.condition === 'string'
}

// Node validation rule structure
interface NodeValidationRule {
  fields: Record<string, any>
  customValidation?: CustomValidation
}

// Validation rules type
type ValidationRules = Record<string, NodeValidationRule>

// Validation rules embedded in frontend for consistency with backend
const VALIDATION_RULES: ValidationRules = {
  router_node: {
    fields: {
      routes: {
        type: 'array',
        required: true,
        minLength: 1,
        errorMessages: {
          required: 'Router node must have at least one route rule',
          type: 'Routes must be an array',
          minLength: 'Router node must have at least one route rule'
        },
        items: {
          type: 'object',
          fields: {
            id: {
              type: 'string',
              required: true,
              errorMessages: {
                required: 'Route rule must have an id',
                type: 'Route rule id must be a string'
              }
            },
            condition: {
              type: 'string',
              required: true,
              minLength: 1,
              errorMessages: {
                required: 'Condition is required',
                type: 'Condition must be a string',
                minLength: 'Condition cannot be empty'
              }
            },
            targetEdgeKey: {
              type: 'string',
              required: true,
              minLength: 1,
              errorMessages: {
                required: 'Target edge key is required',
                type: 'Target edge key must be a string',
                minLength: 'Target edge key cannot be empty'
              }
            },
            label: {
              type: 'string',
              required: true,
              minLength: 1,
              errorMessages: {
                required: 'Route label is required',
                type: 'Route label must be a string',
                minLength: 'Route label cannot be empty'
              }
            }
          }
        }
      },
      defaultRoute: {
        type: 'string',
        required: false,
        errorMessages: {
          type: 'Default route must be a string'
        }
      }
    }
  },
  loop_condition_node: {
    fields: {
      conditionType: {
        type: 'string',
        required: false,
        enum: ['forEach', 'while', 'doWhile'],
        default: 'while',
        errorMessages: {
          enum: "Loop type must be 'forEach', 'while', or 'doWhile'"
        }
      },
      condition: {
        type: 'string',
        required: false,
        conditionalRequired: {
          condition: "conditionType in ['while', 'doWhile'] or conditionType is null",
          errorMessage: 'Condition expression is required for while/doWhile loops'
        },
        errorMessages: {
          type: 'Condition expression must be a string'
        }
      },
      listVariable: {
        type: 'string',
        required: false,
        conditionalRequired: {
          condition: "conditionType == 'forEach'",
          errorMessage: 'List variable is required for forEach loops'
        },
        errorMessages: {
          type: 'List variable must be a string'
        }
      },
      maxIterations: {
        type: 'number',
        required: true,
        minimum: 1,
        maximum: 100,
        errorMessages: {
          required: 'Max iterations is required',
          type: 'Max iterations must be a number',
          minimum: 'Max iterations must be greater than 0',
          maximum: 'Max iterations should not exceed 100'
        }
      }
    }
  },
  tool_node: {
    fields: {
      tool_name: {
        type: 'string',
        required: true,
        minLength: 1,
        errorMessages: {
          required: 'Tool name is required',
          type: 'Tool name must be a string',
          minLength: 'Tool name cannot be empty'
        }
      },
      input_mapping: {
        type: 'object',
        required: false,
        errorMessages: {
          type: 'Input mapping must be an object'
        }
      }
    }
  },
  function_node: {
    fields: {
      function_name: {
        type: 'string',
        required: false,
        exclusiveWith: ['function_code'],
        errorMessages: {
          type: 'Function name must be a string'
        }
      },
      function_code: {
        type: 'string',
        required: false,
        exclusiveWith: ['function_name'],
        errorMessages: {
          type: 'Function code must be a string'
        }
      }
    },
    customValidation: {
      message: 'Either function_name or function_code must be provided',
      condition: 'function_name or function_code'
    }
  },
  aggregator_node: {
    fields: {
      error_strategy: {
        type: 'string',
        required: false,
        enum: ['fail_fast', 'best_effort'],
        default: 'fail_fast',
        errorMessages: {
          enum: "Error strategy must be 'fail_fast' or 'best_effort'"
        }
      }
    }
  },
  json_parser_node: {
    fields: {
      jsonpath_query: {
        type: 'string',
        required: false,
        errorMessages: {
          type: 'JSONPath query must be a string'
        }
      },
      json_schema: {
        type: 'object',
        required: false,
        errorMessages: {
          type: 'JSON Schema must be an object'
        }
      }
    },
    customValidation: {
      message: 'Either jsonpath_query or json_schema must be provided',
      condition: 'jsonpath_query or json_schema'
    }
  },
  http_request_node: {
    fields: {
      method: {
        type: 'string',
        required: false,
        enum: ['GET', 'POST', 'PUT', 'DELETE', 'PATCH'],
        default: 'GET',
        errorMessages: {
          enum: 'Invalid HTTP method'
        }
      },
      url: {
        type: 'string',
        required: true,
        pattern: '^https?://',
        errorMessages: {
          required: 'URL is required',
          type: 'URL must be a string',
          pattern: 'URL must start with http:// or https://'
        }
      },
      headers: {
        type: 'object',
        required: false,
        errorMessages: {
          type: 'Headers must be an object'
        }
      },
      max_retries: {
        type: 'number',
        required: false,
        minimum: 0,
        errorMessages: {
          type: 'Max retries must be a number',
          minimum: 'Max retries must be non-negative'
        }
      },
      timeout: {
        type: 'number',
        required: false,
        minimum: 0.1,
        errorMessages: {
          type: 'Timeout must be a number',
          minimum: 'Timeout must be positive'
        }
      }
    }
  },
  condition_agent: {
    fields: {
      instruction: {
        type: 'string',
        required: true,
        minLength: 1,
        errorMessages: {
          required: 'Routing instruction is required',
          type: 'Routing instruction must be a string',
          minLength: 'Routing instruction cannot be empty'
        }
      },
      options: {
        type: 'array',
        required: false,
        minLength: 1,
        items: {
          type: 'string',
          minLength: 1
        },
        errorMessages: {
          type: 'Options must be an array',
          minLength: 'At least one route option is required'
        },
        itemErrors: {
          type: 'Each option must be a string',
          minLength: 'Each option must be non-empty'
        }
      }
    }
  }
}

function validateField(
  fieldName: string,
  fieldConfig: any,
  value: any,
  config: Record<string, unknown>
): ValidationError[] {
  const errors: ValidationError[] = []

  // Check required
  if (fieldConfig.required && (value === null || value === undefined || value === '')) {
    errors.push({
      field: fieldName,
      message: fieldConfig.errorMessages?.required || `${fieldName} is required`,
      severity: 'error'
    })
    return errors
  }

  // Skip validation if value is empty and not required
  if (value === null || value === undefined || value === '') {
    return errors
  }

  // Pattern validation (new)
  if (fieldConfig.pattern && typeof value === 'string') {
    try {
      const regex = new RegExp(fieldConfig.pattern)
      if (!regex.test(value)) {
        errors.push({
          field: fieldName,
          message: fieldConfig.errorMessages?.pattern || `${fieldName} format is invalid`,
          severity: 'error'
        })
      }
    } catch (e) {
      // Invalid regex pattern, skip validation
    }
  }

  // Max length validation (new)
  if (fieldConfig.maxLength && typeof value === 'string' && value.length > fieldConfig.maxLength) {
    errors.push({
      field: fieldName,
      message: fieldConfig.errorMessages?.maxLength || `${fieldName} must be ${fieldConfig.maxLength} characters or less`,
      severity: 'error'
    })
  }

  // Type check
  const expectedTypes = Array.isArray(fieldConfig.type) ? fieldConfig.type : [fieldConfig.type]
  const isValidType = expectedTypes.some((type: string) => {
    switch (type) {
      case 'string': return typeof value === 'string'
      case 'number': return typeof value === 'number'
      case 'boolean': return typeof value === 'boolean'
      case 'object': return typeof value === 'object' && value !== null
      case 'array': return Array.isArray(value)
      default: return false
    }
  })

  if (!isValidType) {
    errors.push({
      field: fieldName,
      message: fieldConfig.errorMessages?.type || `${fieldName} has invalid type`,
      severity: 'error'
    })
    return errors
  }

  // Number validation
  if ((expectedTypes.includes('number') || fieldConfig.type === 'number') && typeof value === 'number') {
    if (fieldConfig.minimum !== undefined && value < fieldConfig.minimum) {
      errors.push({
        field: fieldName,
        message: fieldConfig.errorMessages?.minimum || `${fieldName} is too small`,
        severity: 'error'
      })
    }
    if (fieldConfig.maximum !== undefined && value > fieldConfig.maximum) {
      errors.push({
        field: fieldName,
        message: fieldConfig.errorMessages?.maximum || `${fieldName} is too large`,
        severity: 'error'
      })
    }
  }

  // String validation
  if ((expectedTypes.includes('string') || fieldConfig.type === 'string') && typeof value === 'string') {
    if (fieldConfig.minLength !== undefined && value.length < fieldConfig.minLength) {
      errors.push({
        field: fieldName,
        message: fieldConfig.errorMessages?.minLength || `${fieldName} is too short`,
        severity: 'error'
      })
    }
  }

  // Enum validation
  if (fieldConfig.enum && !fieldConfig.enum.includes(value)) {
    errors.push({
      field: fieldName,
      message: fieldConfig.errorMessages?.enum || `${fieldName} has invalid value`,
      severity: 'error'
    })
  }

  // Pattern validation
  if (fieldConfig.pattern && typeof value === 'string') {
    const regex = new RegExp(fieldConfig.pattern)
    if (!regex.test(value)) {
      errors.push({
        field: fieldName,
        message: fieldConfig.errorMessages?.pattern || `${fieldName} format is invalid`,
        severity: 'error'
      })
    }
  }

  // Array validation
  if (fieldConfig.type === 'array' && Array.isArray(value)) {
    if (fieldConfig.minLength !== undefined && value.length < fieldConfig.minLength) {
      errors.push({
        field: fieldName,
        message: fieldConfig.errorMessages?.minLength || `${fieldName} needs more items`,
        severity: 'error'
      })
    }

    // Validate array items
    if (fieldConfig.items && fieldConfig.itemErrors) {
      value.forEach((item, index) => {
        const itemFieldName = `${fieldName}[${index}]`
        if (fieldConfig.items.type === 'string' && typeof item !== 'string') {
          errors.push({
            field: itemFieldName,
            message: fieldConfig.itemErrors.type,
            severity: 'error'
          })
        } else if (fieldConfig.items.minLength !== undefined && typeof item === 'string' && item.length < fieldConfig.items.minLength) {
          errors.push({
            field: itemFieldName,
            message: fieldConfig.itemErrors.minLength,
            severity: 'error'
          })
        }
      })
    }
  }

  // Object validation with nested fields
  if (fieldConfig.type === 'object' && fieldConfig.fields && typeof value === 'object') {
    for (const [subFieldName, subFieldConfig] of Object.entries(fieldConfig.fields)) {
      const subValue = (value as any)[subFieldName]
      const subErrors = validateField(`${fieldName}.${subFieldName}`, subFieldConfig, subValue, config)
      errors.push(...subErrors)
    }
  }

  return errors
}

function validateConditionalRequired(
  fieldName: string,
  fieldConfig: any,
  config: Record<string, unknown>
): ValidationError[] {
  const errors: ValidationError[] = []

  if (fieldConfig.conditionalRequired) {
    const { condition, errorMessage } = fieldConfig.conditionalRequired

    // Simple condition evaluation
    let shouldBeRequired = false
    if (condition === "conditionType in ['while', 'doWhile'] or conditionType is null") {
      const conditionType = config.conditionType as string
      shouldBeRequired = ['while', 'doWhile'].includes(conditionType) || conditionType === undefined
    } else if (condition === "conditionType == 'forEach'") {
      shouldBeRequired = config.conditionType === 'forEach'
    }

    if (shouldBeRequired) {
      const value = config[fieldName]
      if (value === null || value === undefined || value === '') {
        errors.push({
          field: fieldName,
          message: errorMessage,
          severity: 'error'
        })
      }
    }
  }

  return errors
}

function validateExclusiveFields(
  fieldName: string,
  fieldConfig: any,
  config: Record<string, unknown>
): ValidationError[] {
  const errors: ValidationError[] = []

  if (fieldConfig.exclusiveWith) {
    const currentValue = config[fieldName]
    if (currentValue !== null && currentValue !== undefined && currentValue !== '') {
      for (const exclusiveField of fieldConfig.exclusiveWith) {
        const exclusiveValue = config[exclusiveField]
        if (exclusiveValue !== null && exclusiveValue !== undefined && exclusiveValue !== '') {
          errors.push({
            field: fieldName,
            message: `Cannot specify both ${fieldName} and ${exclusiveField}`,
            severity: 'error'
          })
          break
        }
      }
    }
  }

  return errors
}

function validateCustomRules(nodeType: string, config: Record<string, unknown>): ValidationError[] {
  const errors: ValidationError[] = []
  const nodeRule = VALIDATION_RULES[nodeType as keyof typeof VALIDATION_RULES]

  if (nodeRule?.customValidation) {
    const customValidation = nodeRule.customValidation

    if (hasRules(customValidation)) {
      // New format with multiple rules
      for (const rule of customValidation.rules) {
        const { name, condition, errorMessage } = rule

        let isValid = false
        if (name === 'unique_target_keys') {
          const routes = config.routes as any[]
          if (routes && Array.isArray(routes)) {
            const targetKeys = routes
              .map((r: any) => r.targetEdgeKey)
              .filter((key: any) => key && typeof key === 'string')
            const uniqueKeys = new Set(targetKeys)
            isValid = uniqueKeys.size === targetKeys.length
          } else {
            isValid = true // No routes, so no duplicates
          }
        } else if (name === 'default_route_not_in_routes') {
          const defaultRoute = config.defaultRoute as string
          const routes = config.routes as any[]
          if (defaultRoute && routes && Array.isArray(routes)) {
            const routeKeys = routes
              .map((r: any) => r.targetEdgeKey)
              .filter((key: any) => key && typeof key === 'string')
            isValid = !routeKeys.includes(defaultRoute)
          } else {
            isValid = true
          }
        }

        if (!isValid) {
          errors.push({
            field: `config.${name}`,
            message: errorMessage,
            severity: 'warning'
          })
        }
      }
    } else if (hasCondition(customValidation)) {
      // Old format for backward compatibility
      const { message, condition } = customValidation

      let isValid = false
      if (condition === 'function_name or function_code') {
        isValid = !!(config.function_name || config.function_code)
      } else if (condition === 'jsonpath_query or json_schema') {
        isValid = !!(config.jsonpath_query || config.json_schema)
      }

      if (!isValid) {
        errors.push({
          field: 'config',
          message,
          severity: 'error'
        })
      }
    }
  }

  return errors
}

export const validateNodeConfig = (
  nodeType: string,
  config: Record<string, unknown>
): ValidationError[] => {
  const errors: ValidationError[] = []

  const nodeRule = VALIDATION_RULES[nodeType as keyof typeof VALIDATION_RULES]
  if (!nodeRule) {
    return errors // No validation rules for this node type
  }

  const fieldsConfig = nodeRule.fields

  // Validate each field
  for (const [fieldName, fieldConfig] of Object.entries(fieldsConfig)) {
    const value = config[fieldName]

    // Basic field validation
    const fieldErrors = validateField(fieldName, fieldConfig, value, config)
    errors.push(...fieldErrors)

    // Conditional required validation
    const conditionalErrors = validateConditionalRequired(fieldName, fieldConfig, config)
    errors.push(...conditionalErrors)

    // Exclusive fields validation
    const exclusiveErrors = validateExclusiveFields(fieldName, fieldConfig, config)
    errors.push(...exclusiveErrors)
  }

  // Custom validation rules
  const customErrors = validateCustomRules(nodeType, config)
  errors.push(...customErrors)

  return errors
}
