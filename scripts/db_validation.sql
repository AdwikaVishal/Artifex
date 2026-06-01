-- Artifex Phase 2 — DB validation scripts

-- Core “non-empty” gates (Phase 2)
SELECT COUNT(*) AS children_count FROM children;
SELECT COUNT(*) AS families_count FROM families;
SELECT COUNT(*) AS placement_history_count FROM placement_history;
SELECT COUNT(*) AS active_placements_count FROM active_placements;

-- Empty table detection (all key tables)
SELECT 'children'              AS table, COUNT(*) AS rows FROM children              UNION ALL
SELECT 'families'              AS table, COUNT(*) AS rows FROM families              UNION ALL
SELECT 'placements'            AS table, COUNT(*) AS rows FROM placements            UNION ALL
SELECT 'placement_predictions' AS table, COUNT(*) AS rows FROM placement_predictions UNION ALL
SELECT 'placement_history'     AS table, COUNT(*) AS rows FROM placement_history     UNION ALL
SELECT 'active_placements'     AS table, COUNT(*) AS rows FROM active_placements     UNION ALL
SELECT 'workflow_events'       AS table, COUNT(*) AS rows FROM workflow_events       UNION ALL
SELECT 'workflow_status'       AS table, COUNT(*) AS rows FROM workflow_status       UNION ALL
SELECT 'ml_inference_logs'     AS table, COUNT(*) AS rows FROM ml_inference_logs
ORDER BY rows ASC;

-- Orphan checks (should be 0 in production)
SELECT COUNT(*) AS placements_missing_child
FROM placements p
LEFT JOIN children c ON c.child_id = p.child_id
WHERE c.child_id IS NULL;

SELECT COUNT(*) AS placements_missing_family_when_matched
FROM placements p
LEFT JOIN families f ON f.family_id = p.family_id
WHERE p.family_id IS NOT NULL
  AND f.family_id IS NULL;

SELECT COUNT(*) AS active_placements_missing_child
FROM active_placements ap
LEFT JOIN children c ON c.child_id = ap.child_id
WHERE c.child_id IS NULL;

SELECT COUNT(*) AS active_placements_missing_family_when_set
FROM active_placements ap
LEFT JOIN families f ON f.family_id = ap.family_id
WHERE ap.family_id IS NOT NULL
  AND f.family_id IS NULL;

-- Capacity sanity (negative should be 0)
SELECT COUNT(*) AS families_negative_capacity
FROM (
  SELECT f.family_id,
         (f.total_capacity - COALESCE(
           (SELECT COUNT(*) FROM active_placements ap WHERE ap.family_id=f.family_id AND ap.status='active'), 0
         )) AS available_capacity
  FROM families f
  WHERE f.active = TRUE
) x
WHERE x.available_capacity < 0;

