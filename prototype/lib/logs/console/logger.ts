/**
 * logger.ts
 *
 * This module provides standardized console logging utilities for internal application logging.
 */

/**
 * LogLevel enum defines the severity levels for logging
 */
export enum LogLevel {
  DEBUG = 'DEBUG',
  INFO = 'INFO',
  WARN = 'WARN',
  ERROR = 'ERROR',
}

/**
 * Get the current environment
 */
const getEnv = () => {
  if (typeof process !== 'undefined' && process.env) {
    return {
      NODE_ENV: process.env.NODE_ENV || 'development',
      LOG_LEVEL: process.env.LOG_LEVEL,
    }
  }
  return {
    NODE_ENV: 'development',
    LOG_LEVEL: undefined,
  }
}

/**
 * Get the minimum log level from environment variable or use defaults
 */
const getMinLogLevel = (): LogLevel => {
  const env = getEnv()
  if (env.LOG_LEVEL) {
    return env.LOG_LEVEL as LogLevel
  }

  switch (env.NODE_ENV) {
    case 'development':
      return LogLevel.DEBUG
    case 'production':
      return LogLevel.ERROR
    case 'test':
      return LogLevel.ERROR
    default:
      return LogLevel.DEBUG
  }
}

/**
 * Configuration for different environments
 */
const LOG_CONFIG = {
  development: {
    enabled: true,
    minLevel: getMinLogLevel(),
    colorize: true,
  },
  production: {
    enabled: true,
    minLevel: getMinLogLevel(),
    colorize: false,
  },
  test: {
    enabled: false,
    minLevel: getMinLogLevel(),
    colorize: false,
  },
}

// Get current environment
const ENV = (getEnv().NODE_ENV || 'development') as keyof typeof LOG_CONFIG
const config = LOG_CONFIG[ENV] || LOG_CONFIG.development

// Format objects for logging
const formatObject = (obj: unknown): string => {
  try {
    if (obj instanceof Error) {
      return JSON.stringify(
        {
          message: obj.message,
          stack: ENV === 'development' ? obj.stack : undefined,
          name: obj.name,
        },
        null,
        ENV === 'development' ? 2 : 0
      )
    }
    return JSON.stringify(obj, null, ENV === 'development' ? 2 : 0)
  } catch {
    return '[Circular or Non-Serializable Object]'
  }
}

/**
 * Logger class for standardized console logging
 */
export class Logger {
  private module: string

  /**
   * Create a new logger for a specific module
   * @param module The name of the module
   */
  constructor(module: string) {
    this.module = module
  }

  /**
   * Determines if a log at the given level should be displayed
   */
  private shouldLog(level: LogLevel): boolean {
    if (!config.enabled) return false

    // In production, only log on server-side (where window is undefined)
    if (ENV === 'production' && typeof window !== 'undefined') {
      return false
    }

    const levels = [LogLevel.DEBUG, LogLevel.INFO, LogLevel.WARN, LogLevel.ERROR]
    const minLevelIndex = levels.indexOf(config.minLevel)
    const currentLevelIndex = levels.indexOf(level)

    return currentLevelIndex >= minLevelIndex
  }

  /**
   * Format arguments for logging, converting objects to JSON strings
   */
  private formatArgs(args: unknown[]): unknown[] {
    return args.map((arg) => {
      if (arg === null || arg === undefined) return arg
      if (typeof arg === 'object') return formatObject(arg)
      return arg
    })
  }

  /**
   * Internal method to log a message with the specified level
   */
  private log(level: LogLevel, message: string, ...args: unknown[]) {
    if (!this.shouldLog(level)) return

    const timestamp = new Date().toISOString()
    const formattedArgs = this.formatArgs(args)
    const prefix = `[${timestamp}] [${level}] [${this.module}]`

    if (level === LogLevel.ERROR) {
      console.error(prefix, message, ...formattedArgs)
    } else if (level === LogLevel.WARN) {
      console.warn(prefix, message, ...formattedArgs)
    } else {
      console.log(prefix, message, ...formattedArgs)
    }
  }

  /**
   * Log a debug message
   */
  debug(message: string, ...args: unknown[]) {
    this.log(LogLevel.DEBUG, message, ...args)
  }

  /**
   * Log an info message
   */
  info(message: string, ...args: unknown[]) {
    this.log(LogLevel.INFO, message, ...args)
  }

  /**
   * Log a warning message
   */
  warn(message: string, ...args: unknown[]) {
    this.log(LogLevel.WARN, message, ...args)
  }

  /**
   * Log an error message
   */
  error(message: string, ...args: unknown[]) {
    this.log(LogLevel.ERROR, message, ...args)
  }
}

/**
 * Create a logger for a specific module
 *
 * @param module The name of the module
 * @returns A Logger instance
 */
export function createLogger(module: string): Logger {
  return new Logger(module)
}
