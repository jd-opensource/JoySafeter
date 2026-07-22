//! Git repository cloning into the sandbox workspace.
//!
//! Mirrors the official Managed Agents `github_repository` resource: each repo is
//! cloned into a `mount_path` under the work_dir. The clone credential
//! (`authorization_token`) is passed to `git` through a transient `GIT_ASKPASS`
//! helper so it never lands in `.git/config`, shell history, or our logs.

use crate::proto::RepoConfig;
use std::path::{Component, Path, PathBuf};
use tracing::info;

/// Clone every configured repo into `work_dir`.
///
/// Repos are declared session resources, so a clone failure must fail setup/task
/// preparation instead of starting the agent with an incomplete workspace.
pub async fn clone_repos(work_dir: &Path, repos: &[RepoConfig]) -> Result<(), String> {
    for repo in repos {
        if repo.url.trim().is_empty() {
            continue;
        }
        clone_one(work_dir, repo)
            .await
            .map_err(|e| format!("clone repo {}: {e}", repo.url))?;
    }
    Ok(())
}

async fn clone_one(work_dir: &Path, repo: &RepoConfig) -> Result<(), String> {
    let dest = resolve_dest(work_dir, repo)?;

    // Idempotency: if the destination is already a git repo, skip re-cloning.
    if dest.join(".git").exists() {
        info!(path = %dest.display(), "Repo already present, skipping clone");
        return Ok(());
    }
    if let Some(parent) = dest.parent() {
        tokio::fs::create_dir_all(parent)
            .await
            .map_err(|e| format!("mkdir {}: {e}", parent.display()))?;
    }

    // Transient askpass helper carries the token via env, not the script body.
    let askpass = AskpassHelper::create(&repo.authorization_token).await?;

    let mut cmd = tokio::process::Command::new("git");
    cmd.arg("clone").arg("--depth").arg("1");
    if !repo.branch.trim().is_empty() {
        cmd.arg("--branch").arg(&repo.branch);
    }
    cmd.arg(&repo.url).arg(&dest);
    cmd.env("GIT_TERMINAL_PROMPT", "0");
    if let Some(helper) = &askpass {
        cmd.env("GIT_ASKPASS", &helper.script_path);
        cmd.env(ASKPASS_TOKEN_ENV, &repo.authorization_token);
    }

    info!(url = %repo.url, branch = %repo.branch, path = %dest.display(), "Cloning repo");
    let output = cmd
        .output()
        .await
        .map_err(|e| format!("spawn git clone: {e}"))?;

    if !output.status.success() {
        // git may echo the URL but never the token (it came via askpass env).
        let stderr = String::from_utf8_lossy(&output.stderr);
        return Err(format!(
            "git clone exited with {}: {}",
            output.status,
            stderr.trim()
        ));
    }
    info!(path = %dest.display(), "Repo cloned");
    Ok(())
}

/// Resolve and validate the clone destination. The destination must stay within
/// `work_dir` and contain no `..` traversal — mirrors the Python `_validate_mount_path`.
fn resolve_dest(work_dir: &Path, repo: &RepoConfig) -> Result<PathBuf, String> {
    let raw = repo.path.trim();
    if raw.is_empty() {
        let name = repo_name_from_url(&repo.url)
            .ok_or_else(|| format!("cannot derive repo name from url: {}", repo.url))?;
        return Ok(work_dir.join(name));
    }

    let candidate = Path::new(raw);
    if candidate
        .components()
        .any(|c| matches!(c, Component::ParentDir))
    {
        return Err(format!("mount path must not contain '..': {raw}"));
    }

    let dest = if candidate.is_absolute() {
        candidate.to_path_buf()
    } else {
        work_dir.join(candidate)
    };

    if !dest.starts_with(work_dir) {
        return Err(format!(
            "mount path {} must be under work_dir {}",
            dest.display(),
            work_dir.display()
        ));
    }
    Ok(dest)
}

/// Derive a directory name from a git URL: last path segment, minus a `.git` suffix.
fn repo_name_from_url(url: &str) -> Option<String> {
    let trimmed = url.trim().trim_end_matches('/');
    let last = trimmed.rsplit(['/', ':']).next()?;
    let name = last.strip_suffix(".git").unwrap_or(last);
    if name.is_empty() {
        None
    } else {
        Some(name.to_string())
    }
}

const ASKPASS_TOKEN_ENV: &str = "JOYSAFETER_GIT_TOKEN";

/// A temporary `GIT_ASKPASS` script. The token is read from an env var at run
/// time, so it is never written to disk. The helper directory is removed on drop.
struct AskpassHelper {
    script_path: PathBuf,
    _dir: tempfile::TempDir,
}

impl AskpassHelper {
    /// Returns `None` (no helper) when there is no token — public repos clone
    /// without credentials.
    async fn create(token: &str) -> Result<Option<Self>, String> {
        if token.trim().is_empty() {
            return Ok(None);
        }
        let dir = tempfile::tempdir().map_err(|e| format!("create askpass tmpdir: {e}"))?;
        let script_path = dir.path().join("askpass.sh");
        // The token is read from an env var at run time — it is never written
        // into the script body. git calls the helper with the prompt as $1:
        // "Username for ..." -> the static user; otherwise -> the token.
        let script = String::from("#!/bin/sh\n")
            + "case \"$1\" in\n"
            + "  Username*) echo \"x-access-token\" ;;\n"
            + "  *) printf '%s' \"$"
            + ASKPASS_TOKEN_ENV
            + "\" ;;\n"
            + "esac\n";
        tokio::fs::write(&script_path, script)
            .await
            .map_err(|e| format!("write askpass script: {e}"))?;
        #[cfg(unix)]
        {
            use std::os::unix::fs::PermissionsExt;
            let perms = std::fs::Permissions::from_mode(0o700);
            tokio::fs::set_permissions(&script_path, perms)
                .await
                .map_err(|e| format!("chmod askpass script: {e}"))?;
        }
        Ok(Some(Self {
            script_path,
            _dir: dir,
        }))
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn repo(url: &str, path: &str) -> RepoConfig {
        RepoConfig {
            url: url.to_string(),
            branch: String::new(),
            path: path.to_string(),
            authorization_token: String::new(),
            mount_name: String::new(),
        }
    }

    #[test]
    fn derives_name_from_url() {
        assert_eq!(
            repo_name_from_url("https://github.com/org/repo.git").unwrap(),
            "repo"
        );
        assert_eq!(
            repo_name_from_url("https://github.com/org/repo").unwrap(),
            "repo"
        );
        assert_eq!(
            repo_name_from_url("git@github.com:org/repo.git").unwrap(),
            "repo"
        );
    }

    #[test]
    fn rejects_traversal() {
        let wd = Path::new("/workspace");
        assert!(resolve_dest(wd, &repo("u", "../escape")).is_err());
        assert!(resolve_dest(wd, &repo("u", "/etc/passwd")).is_err());
    }

    #[test]
    fn resolves_relative_and_absolute_under_workdir() {
        let wd = Path::new("/workspace");
        assert_eq!(
            resolve_dest(wd, &repo("u", "repo")).unwrap(),
            PathBuf::from("/workspace/repo")
        );
        assert_eq!(
            resolve_dest(wd, &repo("u", "/workspace/sub/repo")).unwrap(),
            PathBuf::from("/workspace/sub/repo")
        );
    }

    #[test]
    fn defaults_dest_to_url_name() {
        let wd = Path::new("/workspace");
        assert_eq!(
            resolve_dest(wd, &repo("https://github.com/org/myrepo.git", "")).unwrap(),
            PathBuf::from("/workspace/myrepo")
        );
    }

    #[tokio::test]
    async fn clone_repos_returns_error_for_invalid_mount_path() {
        let dir = tempfile::tempdir().unwrap();
        let err = clone_repos(
            dir.path(),
            &[repo("https://github.com/org/repo.git", "../escape")],
        )
        .await
        .expect_err("invalid repo mount path must fail setup");

        assert!(err.contains("mount path must not contain '..'"));
    }

    #[tokio::test]
    async fn clone_repos_returns_error_when_git_clone_fails() {
        let dir = tempfile::tempdir().unwrap();
        let missing_source = dir.path().join("missing-source.git");
        let err = clone_repos(
            dir.path(),
            &[repo(missing_source.to_string_lossy().as_ref(), "repo")],
        )
        .await
        .expect_err("declared repo clone failure must fail setup");

        assert!(err.contains("clone repo"));
        assert!(!dir.path().join("repo/.git").exists());
    }

    #[tokio::test]
    async fn no_askpass_without_token() {
        assert!(AskpassHelper::create("").await.unwrap().is_none());
    }

    #[tokio::test]
    async fn askpass_script_has_no_token_in_body() {
        let helper = AskpassHelper::create("secret-token-123")
            .await
            .unwrap()
            .unwrap();
        let body = tokio::fs::read_to_string(&helper.script_path)
            .await
            .unwrap();
        assert!(
            !body.contains("secret-token-123"),
            "token must not be in script body"
        );
        assert!(
            body.contains(ASKPASS_TOKEN_ENV),
            "script reads token from env"
        );
    }
}
