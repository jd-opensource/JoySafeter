package status

import (
	"context"
	"fmt"

	"github.com/jackc/pgx/v5"
)

// generationLockKey derives the advisory-lock key text for a (group, generation).
func generationLockKey(groupKey string, generation uint64) string {
	return fmt.Sprintf("%s:%d", groupKey, generation)
}

// withGenerationLock acquires a transaction-scoped advisory lock for the given
// (group, generation) and then runs fn. It serializes aggregate recomputation
// for that generation across every controller replica and connection. Acquiring
// the lock BEFORE the recompute UPDATE is essential: a blocked writer waits here,
// then takes a fresh statement snapshot that includes the prior writer's
// committed ACKs. The lock releases automatically on tx commit or rollback.
func withGenerationLock(ctx context.Context, tx pgx.Tx, groupKey string, generation uint64, fn func() error) error {
	if _, err := tx.Exec(ctx, `SELECT pg_advisory_xact_lock(hashtextextended($1, 0))`, generationLockKey(groupKey, generation)); err != nil {
		return fmt.Errorf("acquire egress generation lock %s/%d: %w", groupKey, generation, err)
	}
	return fn()
}

const recomputeApplyStatusSQL = `
WITH target AS (
	SELECT xds_version, required_type_urls
	FROM joysafeter_egress_apply_status
	WHERE group_key = $1 AND generation = $2 AND state IN ('pending', 'published')
), active_nodes AS (
	SELECT node_id
	FROM joysafeter_egress_node_connections
	WHERE group_key = $1 AND disconnected_at IS NULL AND lease_expires_at > now()
), counts AS (
	SELECT
		(SELECT count(*) FROM active_nodes)::integer AS connected_nodes,
		(
			SELECT count(*)
			FROM joysafeter_egress_node_apply_status ns, target
			WHERE ns.group_key = $1 AND ns.generation = $2
			  AND ns.xds_version = target.xds_version
			  AND ns.status = 'ack'
			  AND ns.node_id IN (SELECT node_id FROM active_nodes)
			  AND ns.type_url IN (SELECT jsonb_array_elements_text(target.required_type_urls))
		)::integer AS acked_acks
)
UPDATE joysafeter_egress_apply_status a
SET connected_nodes = counts.connected_nodes,
	required_acks = counts.connected_nodes * jsonb_array_length(a.required_type_urls),
	acked_acks = counts.acked_acks,
	state = CASE
		WHEN counts.connected_nodes > 0
		 AND counts.acked_acks >= counts.connected_nodes * jsonb_array_length(a.required_type_urls)
		THEN 'applied'
		ELSE 'published'
	END,
	applied_at = CASE
		WHEN counts.connected_nodes > 0
		 AND counts.acked_acks >= counts.connected_nodes * jsonb_array_length(a.required_type_urls)
		THEN COALESCE(a.applied_at, now())
		ELSE a.applied_at
	END,
	updated_at = now()
FROM counts
WHERE a.group_key = $1 AND a.generation = $2 AND a.state IN ('pending', 'published')
`

// recomputeApplyStatus recomputes the aggregate apply-status row for one
// (group, generation) from the global node tables, using the row's own
// xds_version and required_type_urls (so callers need only identify the
// generation, and stale-version ACKs are ignored). It does NOT serialize
// itself; concurrent callers MUST wrap it in withGenerationLock. Terminal rows
// (applied/failed/superseded) are never touched, keeping transitions monotonic.
func recomputeApplyStatus(ctx context.Context, tx pgx.Tx, groupKey string, generation uint64) error {
	if _, err := tx.Exec(ctx, recomputeApplyStatusSQL, groupKey, generation); err != nil {
		return fmt.Errorf("recompute egress apply status %s/%d: %w", groupKey, generation, err)
	}
	return nil
}
