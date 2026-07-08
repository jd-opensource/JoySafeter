use std::sync::Arc;

use bollard::Docker;
use tracing::info;
use uuid::Uuid;

/// Builds custom Docker images from environment package configurations.
///
/// Mirrors the Python `ImageBuilder`. Generates Dockerfiles from package lists
/// (apt, pip, npm, cargo, gem, go) and builds images via Docker API.
pub struct ImageBuilder {
    docker: Arc<Docker>,
    default_base: String,
}

impl ImageBuilder {
    pub fn new(docker: Arc<Docker>, default_base: &str) -> Self {
        Self {
            docker,
            default_base: default_base.to_string(),
        }
    }

    /// Build an environment image from package specifications.
    ///
    /// Returns the built image tag.
    pub async fn build_environment_image(
        &self,
        env_id: Uuid,
        version: i32,
        packages: &EnvironmentPackages,
    ) -> anyhow::Result<Option<String>> {
        if packages.is_empty() {
            return Ok(None);
        }

        let short_id = env_id
            .to_string()
            .split('-')
            .next()
            .unwrap_or("env")
            .to_string();
        let tag = format!("joysafeter/env-{short_id}:v{version}");
        let dockerfile = self.generate_dockerfile(packages);
        let tar_context = self.create_tar_context(&dockerfile)?;

        // Use bollard to build the image
        use bollard::image::BuildImageOptions;
        use futures::StreamExt;

        let options = BuildImageOptions {
            t: tag.clone(),
            rm: true,
            forcerm: true,
            ..Default::default()
        };

        let mut stream = self
            .docker
            .build_image(options, None, Some(tar_context.into()));

        while let Some(result) = stream.next().await {
            match result {
                Ok(output) => {
                    if let Some(err) = output.error {
                        return Err(anyhow::anyhow!("Docker build error: {err}"));
                    }
                }
                Err(e) => {
                    return Err(anyhow::anyhow!("Docker build failed: {e}"));
                }
            }
        }

        info!(tag = tag, "Built environment image");
        Ok(Some(tag))
    }

    fn generate_dockerfile(&self, packages: &EnvironmentPackages) -> String {
        let mut lines = vec![
            format!("FROM {}", self.default_base),
            "USER root".to_string(),
        ];

        if !packages.apt.is_empty() {
            let pkgs = sanitize_packages(&packages.apt).join(" ");
            lines.push(format!(
                "RUN apt-get update && apt-get install -y --no-install-recommends {pkgs} && rm -rf /var/lib/apt/lists/*"
            ));
        }

        if !packages.pip.is_empty() {
            let pkgs = sanitize_packages(&packages.pip).join(" ");
            lines.push(format!("RUN pip install --no-cache-dir {pkgs}"));
        }

        if !packages.npm.is_empty() {
            let pkgs = sanitize_packages(&packages.npm).join(" ");
            lines.push(format!("RUN npm install -g {pkgs}"));
        }

        if !packages.cargo.is_empty() {
            let pkgs = sanitize_packages(&packages.cargo).join(" ");
            lines.push(format!("RUN cargo install {pkgs}"));
        }

        if !packages.gem.is_empty() {
            let pkgs = sanitize_packages(&packages.gem).join(" ");
            lines.push(format!("RUN gem install {pkgs}"));
        }

        if !packages.go.is_empty() {
            for pkg in sanitize_packages(&packages.go) {
                lines.push(format!("RUN go install {pkg}"));
            }
        }

        lines.push("USER agent".to_string());
        lines.join("\n")
    }

    fn create_tar_context(&self, dockerfile: &str) -> anyhow::Result<Vec<u8>> {
        let mut buf = Vec::new();
        {
            let mut ar = tar::Builder::new(&mut buf);

            let dockerfile_bytes = dockerfile.as_bytes();
            let mut header = tar::Header::new_gnu();
            header.set_path("Dockerfile")?;
            header.set_size(dockerfile_bytes.len() as u64);
            header.set_mode(0o644);
            header.set_cksum();
            ar.append(&header, dockerfile_bytes)?;
            ar.finish()?;
        }
        Ok(buf)
    }
}

/// Package specifications for building an environment image.
#[derive(Debug, Clone, Default)]
pub struct EnvironmentPackages {
    pub apt: Vec<String>,
    pub pip: Vec<String>,
    pub npm: Vec<String>,
    pub cargo: Vec<String>,
    pub gem: Vec<String>,
    pub go: Vec<String>,
}

impl EnvironmentPackages {
    pub fn is_empty(&self) -> bool {
        self.apt.is_empty()
            && self.pip.is_empty()
            && self.npm.is_empty()
            && self.cargo.is_empty()
            && self.gem.is_empty()
            && self.go.is_empty()
    }

    /// Parse from a JSON environment config value.
    pub fn from_config(config: &serde_json::Value) -> Self {
        let parse_list = |key: &str| -> Vec<String> {
            config
                .get("packages")
                .and_then(|p| p.get(key))
                .and_then(|v| v.as_array())
                .map(|arr| {
                    arr.iter()
                        .filter_map(|v| v.as_str().map(String::from))
                        .collect()
                })
                .unwrap_or_default()
        };

        Self {
            apt: parse_list("apt"),
            pip: parse_list("pip"),
            npm: parse_list("npm"),
            cargo: parse_list("cargo"),
            gem: parse_list("gem"),
            go: parse_list("go"),
        }
    }
}

/// Validate and sanitize package names.
fn sanitize_packages(packages: &[String]) -> Vec<String> {
    let safe_pattern =
        regex_lite::Regex::new(r"^[a-zA-Z0-9][a-zA-Z0-9._\-\[\]@/:>=<>!,~^*]+$").unwrap();

    packages
        .iter()
        .filter(|p| safe_pattern.is_match(p))
        .cloned()
        .collect()
}
