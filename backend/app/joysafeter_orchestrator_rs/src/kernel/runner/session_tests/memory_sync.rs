use super::*;
#[tokio::test]
async fn memory_sync_rejects_archived_store_without_mutating_existing_memory() {
    let Some(pool) = test_pool().await else {
        return;
    };
    let (agent_id, session_id) = create_agent_and_session(&pool).await;
    let store_id = create_mounted_memory_store(&pool, session_id).await;

    let result = async {
        handle_memory_sync_db(
            &pool,
            Some(session_id),
            "main",
            "/notes.txt",
            "first",
            "modified",
            2000,
        )
        .await;

        let (content, version): (String, i32) = sqlx::query_as(
            r#"
                SELECT content, version
                FROM joysafeter_memories
                WHERE store_id = $1 AND path = '/notes.txt'
                "#,
        )
        .bind(store_id)
        .fetch_one(&pool)
        .await
        .expect("active memory sync creates memory");
        assert_eq!(content, "first");
        assert_eq!(version, 1);

        let version_count: i64 = sqlx::query_scalar(
            "SELECT COUNT(*) FROM joysafeter_memory_versions WHERE store_id = $1",
        )
        .bind(store_id)
        .fetch_one(&pool)
        .await
        .expect("count memory versions after create");
        assert_eq!(version_count, 1);

        sqlx::query("UPDATE joysafeter_memory_stores SET archived_at = NOW() WHERE id = $1")
            .bind(store_id)
            .execute(&pool)
            .await
            .expect("archive memory store");

        handle_memory_sync_db(
            &pool,
            Some(session_id),
            "main",
            "/notes.txt",
            "second",
            "modified",
            2000,
        )
        .await;
        handle_memory_sync_db(
            &pool,
            Some(session_id),
            "main",
            "/notes.txt",
            "",
            "delete",
            2000,
        )
        .await;

        let (content_after, version_after): (String, i32) = sqlx::query_as(
            r#"
                SELECT content, version
                FROM joysafeter_memories
                WHERE store_id = $1 AND path = '/notes.txt'
                "#,
        )
        .bind(store_id)
        .fetch_one(&pool)
        .await
        .expect("archived memory sync leaves existing memory intact");
        assert_eq!(content_after, "first");
        assert_eq!(version_after, 1);

        let version_count_after_archive: i64 = sqlx::query_scalar(
            "SELECT COUNT(*) FROM joysafeter_memory_versions WHERE store_id = $1",
        )
        .bind(store_id)
        .fetch_one(&pool)
        .await
        .expect("count memory versions after archived writes");
        assert_eq!(version_count_after_archive, 1);
    }
    .await;

    cleanup_memory_store(&pool, session_id, store_id).await;
    cleanup(&pool, agent_id, session_id).await;
    result
}
