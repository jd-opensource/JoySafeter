/**
 * Backward-compatibility shim.
 *
 * New code should import useGraphStore / useSaveStore / useBuilderUIStore directly.
 * This re-export will be removed once all consumers are migrated.
 */
export { useGraphStore as useBuilderStore } from './graphStore'
