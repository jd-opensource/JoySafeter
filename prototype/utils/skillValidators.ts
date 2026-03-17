/**
 * Skill validation utilities per Agent Skills specification.
 *
 * Reference: https://agentskills.io/specification
 */

// Agent Skills specification constraints
export const MAX_SKILL_NAME_LENGTH = 64;
export const MAX_SKILL_DESCRIPTION_LENGTH = 1024;
export const MAX_COMPATIBILITY_LENGTH = 500;

// Skill name validation regex: lowercase alphanumeric with single hyphens
const SKILL_NAME_REGEX = /^[a-z0-9]+(-[a-z0-9]+)*$/;

export interface ValidationResult {
  valid: boolean;
  error?: string;
}

/**
 * Validate skill name per Agent Skills specification.
 *
 * Requirements:
 * - Max 64 characters
 * - Lowercase alphanumeric and hyphens only (a-z, 0-9, -)
 * - Cannot start or end with hyphen
 * - No consecutive hyphens
 *
 * @param name - Skill name to validate
 * @param directoryName - Optional directory name for matching validation
 * @returns Validation result with error message if invalid
 */
export function validateSkillName(
  name: string,
  directoryName?: string
): ValidationResult {
  if (!name) {
    return { valid: false, error: 'Skill name is required' };
  }

  if (name.length > MAX_SKILL_NAME_LENGTH) {
    return {
      valid: false,
      error: `Skill name must be ${MAX_SKILL_NAME_LENGTH} characters or less (current: ${name.length})`,
    };
  }

  if (!SKILL_NAME_REGEX.test(name)) {
    return {
      valid: false,
      error: 'Skill name must be lowercase alphanumeric with single hyphens only (e.g., "web-research", "data-analysis")',
    };
  }

  if (directoryName && name !== directoryName) {
    return {
      valid: false,
      error: `Skill name "${name}" must match directory name "${directoryName}"`,
    };
  }

  return { valid: true };
}

/**
 * Validate skill description length per Agent Skills specification.
 *
 * Requirements:
 * - Max 1024 characters
 *
 * @param description - Skill description to validate
 * @returns Validation result with error message if invalid
 */
export function validateSkillDescription(description: string): ValidationResult {
  if (!description) {
    return { valid: false, error: 'Skill description is required' };
  }

  if (description.length > MAX_SKILL_DESCRIPTION_LENGTH) {
    return {
      valid: false,
      error: `Skill description must be ${MAX_SKILL_DESCRIPTION_LENGTH} characters or less (current: ${description.length})`,
    };
  }

  return { valid: true };
}

/**
 * Validate compatibility field length per Agent Skills specification.
 *
 * Requirements:
 * - Max 500 characters (if provided)
 *
 * @param compatibility - Compatibility string (optional)
 * @returns Validation result with error message if invalid
 */
export function validateCompatibility(compatibility?: string): ValidationResult {
  if (!compatibility) {
    return { valid: true }; // Optional field
  }

  if (compatibility.length > MAX_COMPATIBILITY_LENGTH) {
    return {
      valid: false,
      error: `Compatibility must be ${MAX_COMPATIBILITY_LENGTH} characters or less (current: ${compatibility.length})`,
    };
  }

  return { valid: true };
}

/**
 * Truncate description to max length if needed.
 *
 * @param description - Skill description
 * @returns Truncated description (if needed) or original description
 */
export function truncateDescription(description: string): string {
  if (description.length > MAX_SKILL_DESCRIPTION_LENGTH) {
    return description.substring(0, MAX_SKILL_DESCRIPTION_LENGTH);
  }
  return description;
}

/**
 * Truncate compatibility to max length if needed.
 *
 * @param compatibility - Compatibility string (optional)
 * @returns Truncated compatibility (if needed) or original compatibility
 */
export function truncateCompatibility(compatibility?: string): string | undefined {
  if (!compatibility) {
    return undefined;
  }

  if (compatibility.length > MAX_COMPATIBILITY_LENGTH) {
    return compatibility.substring(0, MAX_COMPATIBILITY_LENGTH);
  }
  return compatibility;
}

/**
 * Normalize skill name to valid format (lowercase, replace spaces/invalid chars with hyphens).
 *
 * This is a helper function to help users create valid skill names.
 *
 * @param name - Original skill name
 * @returns Normalized skill name
 */
export function normalizeSkillName(name: string): string {
  return name
    .toLowerCase()
    .trim()
    .replace(/[^a-z0-9-]/g, '-') // Replace invalid chars with hyphens
    .replace(/-+/g, '-') // Replace multiple hyphens with single hyphen
    .replace(/^-|-$/g, ''); // Remove leading/trailing hyphens
}
