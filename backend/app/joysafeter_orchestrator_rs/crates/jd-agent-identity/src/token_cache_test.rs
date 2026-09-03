use super::*;

#[test]
fn agent_token_key_is_scoped_to_task_endpoint_and_actor() {
    let key = |user: &str, task: &str, endpoint: &str| {
        agent_token_key(
            "platform",
            "project",
            user,
            "agent",
            "session",
            task,
            endpoint,
            "api.example.com",
        )
    };

    assert_ne!(
        key("user-a", "task-a", "https://api/a"),
        key("user-b", "task-a", "https://api/a")
    );
    assert_ne!(
        key("user-a", "task-a", "https://api/a"),
        key("user-a", "task-b", "https://api/a")
    );
    assert_ne!(
        key("user-a", "task-a", "https://api/a"),
        key("user-a", "task-a", "https://api/b")
    );
}
