use anyhow::{bail, Context};
use std::path::PathBuf;
use std::process::Command;

pub fn open_in_editor(content: &str, filename: &str) -> anyhow::Result<String> {
    let editor = std::env::var("EDITOR")
        .or_else(|_| std::env::var("VISUAL"))
        .unwrap_or_else(|_| "vi".to_string());

    let dir = tempfile::tempdir().context("Failed to create temp dir")?;
    let path = dir.path().join(filename);
    std::fs::write(&path, content).context("Failed to write temp file")?;

    run_editor(&editor, &path)?;

    let edited = std::fs::read_to_string(&path).context("Failed to read edited file")?;
    Ok(edited)
}

fn run_editor(editor: &str, path: &PathBuf) -> anyhow::Result<()> {
    let mut parts = editor.split_whitespace();
    let program = parts.next().unwrap_or("vi");
    let status = Command::new(program)
        .args(parts)
        .arg(path)
        .status()
        .with_context(|| format!("Failed to launch editor: {editor}"))?;

    if !status.success() {
        bail!("Editor exited with non-zero status");
    }
    Ok(())
}
