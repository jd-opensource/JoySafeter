use crate::client::JoysafeterClient;
use crate::output::print_table;
use crate::OutputFormat;

pub async fn whoami(client: &JoysafeterClient, format: &OutputFormat) -> anyhow::Result<()> {
    let me = client.whoami().await?;
    match format {
        OutputFormat::Json => println!("{}", serde_json::to_string_pretty(&me)?),
        OutputFormat::Table => {
            let user = me.get("user").unwrap_or(&serde_json::Value::Null);
            let org = me.get("organization").unwrap_or(&serde_json::Value::Null);
            let project = me.get("project").unwrap_or(&serde_json::Value::Null);
            let rows = vec![
                vec![
                    "User".to_string(),
                    user["id"].as_str().unwrap_or("-").to_string(),
                    user["email"].as_str().unwrap_or("-").to_string(),
                ],
                vec![
                    "Organization".to_string(),
                    org["id"].as_str().unwrap_or("-").to_string(),
                    org["name"].as_str().unwrap_or("-").to_string(),
                ],
                vec![
                    "Project".to_string(),
                    project["id"].as_str().unwrap_or("-").to_string(),
                    project["name"].as_str().unwrap_or("-").to_string(),
                ],
                vec![
                    "Role".to_string(),
                    org["role"]
                        .as_str()
                        .or_else(|| me["role"].as_str())
                        .unwrap_or("-")
                        .to_string(),
                    String::new(),
                ],
            ];
            print_table(&["KIND", "ID", "NAME"], &rows);
        }
    }
    Ok(())
}
