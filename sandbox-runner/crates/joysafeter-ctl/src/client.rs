use anyhow::{bail, Context};
use reqwest::{Method, StatusCode};

pub struct JoysafeterClient {
    base_url: String,
    api_key: Option<String>,
    http: reqwest::Client,
}

fn extract_data(val: serde_json::Value) -> serde_json::Value {
    if val.get("success").and_then(|v| v.as_bool()) == Some(true) {
        if let Some(data) = val.get("data") {
            return data.clone();
        }
    }
    val
}

fn extract_data_array(val: serde_json::Value) -> Vec<serde_json::Value> {
    let val = extract_data(val);
    if let Some(arr) = val.as_array() {
        return arr.clone();
    }
    if let Some(data) = val.get("data").and_then(|d| d.as_array()) {
        return data.clone();
    }
    vec![val]
}

impl JoysafeterClient {
    pub fn new(base_url: &str, api_key: Option<String>) -> Self {
        Self {
            base_url: normalize_base_url(base_url),
            api_key: api_key.filter(|v| !v.trim().is_empty()),
            http: reqwest::Client::new(),
        }
    }

    fn request(&self, method: Method, path: &str) -> reqwest::RequestBuilder {
        let url = format!("{}{}", self.base_url, path);
        let mut req = self.http.request(method, url);
        if let Some(api_key) = &self.api_key {
            req = req.header("X-Api-Key", api_key);
        }
        req
    }

    async fn send_json(
        &self,
        method: Method,
        path: &str,
        body: Option<&serde_json::Value>,
    ) -> anyhow::Result<serde_json::Value> {
        let mut req = self.request(method.clone(), path);
        if let Some(body) = body {
            req = req.json(body);
        }
        let resp = req
            .send()
            .await
            .context("Failed to connect to joysafeter")?;
        let status = resp.status();
        let text = resp.text().await.unwrap_or_default();
        if !status.is_success() {
            if status == StatusCode::UNAUTHORIZED {
                bail!(
                    "{} {} failed ({}): authentication required. Set JOYSAFETER_API_KEY or pass --api-key. {}",
                    method,
                    path,
                    status,
                    text
                );
            }
            bail!("{} {} failed ({}): {}", method, path, status, text);
        }
        if text.trim().is_empty() {
            return Ok(serde_json::Value::Null);
        }
        let val: serde_json::Value = serde_json::from_str(&text)
            .with_context(|| format!("Failed to parse response from {} {}", method, path))?;
        Ok(extract_data(val))
    }

    async fn get_array(&self, path: &str) -> anyhow::Result<Vec<serde_json::Value>> {
        let val = self.send_json(Method::GET, path, None).await?;
        Ok(extract_data_array(val))
    }

    pub async fn whoami(&self) -> anyhow::Result<serde_json::Value> {
        self.send_json(Method::GET, "/auth/me", None).await
    }

    // --- Agents ---

    pub async fn list_agents(&self) -> anyhow::Result<Vec<serde_json::Value>> {
        self.get_array("/agents?limit=100").await
    }

    pub async fn get_agent_by_name(&self, name: &str) -> anyhow::Result<Option<serde_json::Value>> {
        let agents = self.list_agents().await?;
        Ok(agents
            .into_iter()
            .find(|a| a["name"].as_str() == Some(name)))
    }

    pub async fn create_agent(
        &self,
        body: &serde_json::Value,
    ) -> anyhow::Result<serde_json::Value> {
        self.send_json(Method::POST, "/agents", Some(body)).await
    }

    pub async fn update_agent(
        &self,
        id: &str,
        body: &serde_json::Value,
    ) -> anyhow::Result<serde_json::Value> {
        self.send_json(Method::POST, &format!("/agents/{}", id), Some(body))
            .await
    }

    pub async fn delete_agent(&self, id: &str, force: bool) -> anyhow::Result<()> {
        let path = if force {
            format!("/agents/{}?force=true", id)
        } else {
            format!("/agents/{}", id)
        };
        self.send_json(Method::DELETE, &path, None).await?;
        Ok(())
    }

    // --- Tasks ---

    pub async fn create_task(&self, body: &serde_json::Value) -> anyhow::Result<serde_json::Value> {
        self.send_json(Method::POST, "/tasks", Some(body)).await
    }

    pub async fn get_task(&self, id: &str) -> anyhow::Result<serde_json::Value> {
        self.send_json(Method::GET, &format!("/tasks/{}", id), None)
            .await
    }

    pub async fn list_tasks_by_agent(
        &self,
        agent_id: &str,
    ) -> anyhow::Result<Vec<serde_json::Value>> {
        self.get_array(&format!("/agents/{}/tasks", agent_id)).await
    }

    pub async fn cancel_task(&self, id: &str) -> anyhow::Result<()> {
        self.send_json(Method::POST, &format!("/tasks/{}/cancel", id), None)
            .await?;
        Ok(())
    }

    // --- Secrets ---

    pub async fn list_secrets(&self) -> anyhow::Result<Vec<serde_json::Value>> {
        self.get_array("/secrets?limit=100").await
    }

    pub async fn get_secret_by_name(
        &self,
        name: &str,
    ) -> anyhow::Result<Option<serde_json::Value>> {
        let secrets = self.list_secrets().await?;
        Ok(secrets
            .into_iter()
            .find(|s| s["name"].as_str() == Some(name)))
    }

    pub async fn create_secret(
        &self,
        body: &serde_json::Value,
    ) -> anyhow::Result<serde_json::Value> {
        self.send_json(Method::POST, "/secrets", Some(body)).await
    }

    pub async fn update_secret(
        &self,
        id: &str,
        body: &serde_json::Value,
    ) -> anyhow::Result<serde_json::Value> {
        self.send_json(Method::PUT, &format!("/secrets/{}", id), Some(body))
            .await
    }

    pub async fn delete_secret(&self, id: &str, force: bool) -> anyhow::Result<()> {
        let path = if force {
            format!("/secrets/{}?force=true", id)
        } else {
            format!("/secrets/{}", id)
        };
        self.send_json(Method::DELETE, &path, None).await?;
        Ok(())
    }

    // --- Environments ---

    pub async fn list_environments(&self) -> anyhow::Result<Vec<serde_json::Value>> {
        self.get_array("/environments?limit=100").await
    }

    pub async fn get_environment_by_name(
        &self,
        name: &str,
    ) -> anyhow::Result<Option<serde_json::Value>> {
        let envs = self.list_environments().await?;
        Ok(envs.into_iter().find(|e| e["name"].as_str() == Some(name)))
    }

    pub async fn create_environment(
        &self,
        body: &serde_json::Value,
    ) -> anyhow::Result<serde_json::Value> {
        self.send_json(Method::POST, "/environments", Some(body))
            .await
    }

    pub async fn update_environment(
        &self,
        id: &str,
        body: &serde_json::Value,
    ) -> anyhow::Result<serde_json::Value> {
        self.send_json(Method::POST, &format!("/environments/{}", id), Some(body))
            .await
    }

    pub async fn delete_environment(&self, id: &str) -> anyhow::Result<()> {
        self.send_json(Method::DELETE, &format!("/environments/{}", id), None)
            .await?;
        Ok(())
    }

    // --- Sessions ---

    pub async fn list_sessions(
        &self,
        limit: Option<i64>,
        agent_id: Option<&str>,
    ) -> anyhow::Result<Vec<serde_json::Value>> {
        if let Some(agent_id) = agent_id {
            return self
                .get_array(&format!(
                    "/agents/{}/sessions?limit={}",
                    agent_id,
                    limit.unwrap_or(50)
                ))
                .await;
        }
        self.get_array(&format!("/sessions?limit={}", limit.unwrap_or(50)))
            .await
    }

    pub async fn get_session(&self, id: &str) -> anyhow::Result<serde_json::Value> {
        self.send_json(Method::GET, &format!("/sessions/{}", id), None)
            .await
    }

    pub async fn delete_session(&self, id: &str) -> anyhow::Result<()> {
        self.send_json(Method::DELETE, &format!("/sessions/{}", id), None)
            .await?;
        Ok(())
    }

    pub async fn create_session(
        &self,
        body: &serde_json::Value,
    ) -> anyhow::Result<serde_json::Value> {
        self.send_json(Method::POST, "/sessions", Some(body)).await
    }

    pub async fn send_event(
        &self,
        session_id: &str,
        body: &serde_json::Value,
    ) -> anyhow::Result<serde_json::Value> {
        self.send_json(
            Method::POST,
            &format!("/sessions/{}/events", session_id),
            Some(body),
        )
        .await
    }

    pub async fn list_events(
        &self,
        session_id: &str,
        limit: Option<i64>,
    ) -> anyhow::Result<Vec<serde_json::Value>> {
        self.list_events_after(session_id, None, limit).await
    }

    pub async fn list_events_after(
        &self,
        session_id: &str,
        after_seq: Option<i64>,
        limit: Option<i64>,
    ) -> anyhow::Result<Vec<serde_json::Value>> {
        let mut path = format!(
            "/sessions/{}/events?limit={}",
            session_id,
            limit.unwrap_or(100)
        );
        if let Some(seq) = after_seq {
            path.push_str(&format!("&after_seq={}", seq));
        }
        self.get_array(&path).await
    }

    // --- Memory Stores ---

    pub async fn list_memory_stores(&self) -> anyhow::Result<Vec<serde_json::Value>> {
        self.get_array("/memory_stores?limit=100").await
    }

    pub async fn get_memory_store(&self, id: &str) -> anyhow::Result<serde_json::Value> {
        self.send_json(Method::GET, &format!("/memory_stores/{}", id), None)
            .await
    }

    pub async fn create_memory_store(
        &self,
        body: &serde_json::Value,
    ) -> anyhow::Result<serde_json::Value> {
        self.send_json(Method::POST, "/memory_stores", Some(body))
            .await
    }

    pub async fn delete_memory_store(&self, id: &str) -> anyhow::Result<()> {
        self.send_json(Method::DELETE, &format!("/memory_stores/{}", id), None)
            .await?;
        Ok(())
    }

    pub async fn update_memory_store(
        &self,
        id: &str,
        body: &serde_json::Value,
    ) -> anyhow::Result<serde_json::Value> {
        self.send_json(Method::POST, &format!("/memory_stores/{}", id), Some(body))
            .await
    }

    #[allow(dead_code)]
    pub async fn archive_memory_store(&self, id: &str) -> anyhow::Result<serde_json::Value> {
        self.send_json(
            Method::POST,
            &format!("/memory_stores/{}/archive", id),
            None,
        )
        .await
    }

    pub async fn list_memories(&self, store_id: &str) -> anyhow::Result<Vec<serde_json::Value>> {
        self.get_array(&format!("/memory_stores/{}/memories?limit=100", store_id))
            .await
    }

    pub async fn get_memory(
        &self,
        store_id: &str,
        memory_id: &str,
    ) -> anyhow::Result<serde_json::Value> {
        self.send_json(
            Method::GET,
            &format!("/memory_stores/{}/memories/{}", store_id, memory_id),
            None,
        )
        .await
    }

    pub async fn create_memory(
        &self,
        store_id: &str,
        body: &serde_json::Value,
    ) -> anyhow::Result<serde_json::Value> {
        self.send_json(
            Method::POST,
            &format!("/memory_stores/{}/memories", store_id),
            Some(body),
        )
        .await
    }

    #[allow(dead_code)]
    pub async fn update_memory(
        &self,
        store_id: &str,
        memory_id: &str,
        body: &serde_json::Value,
    ) -> anyhow::Result<serde_json::Value> {
        self.send_json(
            Method::POST,
            &format!("/memory_stores/{}/memories/{}", store_id, memory_id),
            Some(body),
        )
        .await
    }

    pub async fn delete_memory(&self, store_id: &str, memory_id: &str) -> anyhow::Result<()> {
        self.send_json(
            Method::DELETE,
            &format!("/memory_stores/{}/memories/{}", store_id, memory_id),
            None,
        )
        .await?;
        Ok(())
    }

    pub async fn list_memory_versions(
        &self,
        store_id: &str,
    ) -> anyhow::Result<Vec<serde_json::Value>> {
        self.get_array(&format!(
            "/memory_stores/{}/memory_versions?limit=100",
            store_id
        ))
        .await
    }

    // --- Vaults ---

    pub async fn list_vaults(&self) -> anyhow::Result<Vec<serde_json::Value>> {
        self.get_array("/vaults?limit=100").await
    }

    pub async fn get_vault(&self, id: &str) -> anyhow::Result<serde_json::Value> {
        self.send_json(Method::GET, &format!("/vaults/{}", id), None)
            .await
    }

    pub async fn create_vault(
        &self,
        body: &serde_json::Value,
    ) -> anyhow::Result<serde_json::Value> {
        self.send_json(Method::POST, "/vaults", Some(body)).await
    }

    pub async fn delete_vault(&self, id: &str) -> anyhow::Result<()> {
        self.send_json(Method::DELETE, &format!("/vaults/{}", id), None)
            .await?;
        Ok(())
    }

    pub async fn list_vault_credentials(
        &self,
        vault_id: &str,
    ) -> anyhow::Result<Vec<serde_json::Value>> {
        self.get_array(&format!("/vaults/{}/credentials?limit=100", vault_id))
            .await
    }

    pub async fn create_vault_credential(
        &self,
        vault_id: &str,
        body: &serde_json::Value,
    ) -> anyhow::Result<serde_json::Value> {
        self.send_json(
            Method::POST,
            &format!("/vaults/{}/credentials", vault_id),
            Some(body),
        )
        .await
    }

    pub async fn delete_vault_credential(
        &self,
        vault_id: &str,
        cred_id: &str,
    ) -> anyhow::Result<()> {
        self.send_json(
            Method::DELETE,
            &format!("/vaults/{}/credentials/{}", vault_id, cred_id),
            None,
        )
        .await?;
        Ok(())
    }
}

fn normalize_base_url(base_url: &str) -> String {
    let trimmed = base_url.trim_end_matches('/');
    if trimmed.ends_with("/api/v2") {
        trimmed.to_string()
    } else {
        format!("{}/api/v2", trimmed)
    }
}
