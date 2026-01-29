/**
 * Button Component
 *
 * A reusable, accessible button component with multiple variants and sizes.
 * Supports loading states, disabled states, and keyboard navigation.
 *
 * @example
 * ```tsx
 * <Button variant="primary" size="md" onClick={handleClick}>
 *   Click me
 * </Button>
 * ```
 *
 * @module components/ui/Button
 */

import clsx from 'clsx';
import React, { ButtonHTMLAttributes, ReactNode } from 'react';

/**
 * Button variant types
 */
export type ButtonVariant = 'primary' | 'secondary' | 'danger' | 'ghost';

/**
 * Button size types
 */
export type ButtonSize = 'sm' | 'md' | 'lg';

/**
 * Button component props
 */
export interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
    /** Visual variant of the button */
    variant?: ButtonVariant;

    /** Size of the button */
    size?: ButtonSize;

    /** Whether the button is in a loading state */
    isLoading?: boolean;

    /** Loading indicator content */
    loadingContent?: ReactNode;

    /** Full width button */
    fullWidth?: boolean;

    /** Button content */
    children: ReactNode;
}

/**
 * Reusable Button component with accessibility support
 *
 * Features:
 * - Multiple variants (primary, secondary, danger, ghost)
 * - Multiple sizes (sm, md, lg)
 * - Loading state with spinner
 * - Full width option
 * - Keyboard accessible
 * - Proper ARIA attributes
 *
 * @param props - Button component props
 * @returns Rendered button element
 */
export const Button = React.forwardRef<HTMLButtonElement, ButtonProps>(
    (
        {
            variant = 'primary',
            size = 'md',
            isLoading = false,
            loadingContent = 'Loading...',
            fullWidth = false,
            className,
            disabled,
            children,
            ...rest
        },
        ref,
    ): React.ReactElement => {
        const isDisabled = disabled || isLoading;

        const baseStyles = clsx(
            'inline-flex items-center justify-center font-medium transition-colors duration-200',
            'focus:outline-none focus:ring-2 focus:ring-offset-2',
            'disabled:opacity-50 disabled:cursor-not-allowed',
            fullWidth && 'w-full',
        );

        const variantStyles = {
            primary: clsx(
                'bg-blue-600 text-white hover:bg-blue-700',
                'focus:ring-blue-500',
                'active:bg-blue-800',
            ),
            secondary: clsx(
                'bg-gray-200 text-gray-900 hover:bg-gray-300',
                'focus:ring-gray-400',
                'active:bg-gray-400',
            ),
            danger: clsx(
                'bg-red-600 text-white hover:bg-red-700',
                'focus:ring-red-500',
                'active:bg-red-800',
            ),
            ghost: clsx(
                'bg-transparent text-gray-700 hover:bg-gray-100',
                'focus:ring-gray-400',
                'active:bg-gray-200',
            ),
        };

        const sizeStyles = {
            sm: 'px-3 py-1.5 text-sm',
            md: 'px-4 py-2 text-base',
            lg: 'px-6 py-3 text-lg',
        };

        return (
            <button
                ref={ref}
                type="button"
                disabled={isDisabled}
                className={clsx(baseStyles, variantStyles[variant], sizeStyles[size], className)}
                aria-busy={isLoading}
                aria-disabled={isDisabled}
                {...rest}
            >
                {isLoading ? loadingContent : children}
            </button>
        );
    },
);

Button.displayName = 'Button';

