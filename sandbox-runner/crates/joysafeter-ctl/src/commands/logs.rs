use crate::client::JoysafeterClient;
use std::time::Duration;

pub async fn run(
    client: &JoysafeterClient,
    task_id: &str,
    follow: bool,
    interval: u64,
) -> anyhow::Result<()> {
    let mut last_output_len = 0;

    loop {
        let task = client.get_task(task_id).await?;
        let output = task["output"].as_str().unwrap_or("");
        let status = task["status"].as_str().unwrap_or("unknown");

        if output.len() > last_output_len {
            print!("{}", &output[last_output_len..]);
            last_output_len = output.len();
        }

        let is_terminal = matches!(
            status,
            "completed" | "failed" | "aborted" | "timeout" | "cancelled"
        );

        if is_terminal {
            if let Some(err) = task["error"].as_str() {
                if !err.is_empty() {
                    eprintln!("\n--- Error ---\n{}", err);
                }
            }
            eprintln!("\n[Task {} — status: {}]", task_id, status);
            break;
        }

        if !follow {
            if !output.is_empty() {
                eprintln!(
                    "\n[Task {} — status: {} (use --follow to wait)]",
                    task_id, status
                );
            } else {
                eprintln!(
                    "[Task {} — status: {} (no output yet, use --follow to wait)]",
                    task_id, status
                );
            }
            break;
        }

        tokio::time::sleep(Duration::from_secs(interval)).await;
    }

    Ok(())
}
