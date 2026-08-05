use crate::proto::{self, RunnerMessage};
use fuser::{
    FileAttr, FileType, Filesystem, MountOption, ReplyAttr, ReplyCreate, ReplyData, ReplyDirectory,
    ReplyEmpty, ReplyEntry, ReplyWrite, Request,
};
use std::collections::HashMap;
use std::ffi::OsStr;
use std::path::PathBuf;
use std::sync::atomic::{AtomicU64, Ordering};
use std::sync::{Arc, RwLock};
use std::time::{Duration, SystemTime};
use tokio::sync::mpsc;
use tracing::{info, warn};

const TTL: Duration = Duration::from_secs(1);
const ROOT_INODE: u64 = 1;
const BLOCK_SIZE: u32 = 512;

#[derive(Clone)]
struct InMemoryFile {
    content: Vec<u8>,
    created_at: SystemTime,
    modified_at: SystemTime,
}

struct SyncRequest {
    mount_name: String,
    relative_path: String,
    content: Vec<u8>,
    operation: String,
}

pub struct MemoryFuseFs {
    read_write: bool,
    mount_name: String,
    files: Arc<RwLock<HashMap<String, InMemoryFile>>>,
    inode_to_path: Arc<RwLock<HashMap<u64, String>>>,
    path_to_inode: Arc<RwLock<HashMap<String, u64>>>,
    next_inode: Arc<AtomicU64>,
    sync_tx: std::sync::mpsc::Sender<SyncRequest>,
}

impl MemoryFuseFs {
    fn allocate_inode(&self) -> u64 {
        self.next_inode.fetch_add(1, Ordering::SeqCst)
    }

    fn get_or_create_inode(&self, path: &str) -> u64 {
        let p2i = self.path_to_inode.read().unwrap();
        if let Some(&ino) = p2i.get(path) {
            return ino;
        }
        drop(p2i);
        let ino = self.allocate_inode();
        self.path_to_inode
            .write()
            .unwrap()
            .insert(path.to_string(), ino);
        self.inode_to_path
            .write()
            .unwrap()
            .insert(ino, path.to_string());
        ino
    }

    fn get_path(&self, ino: u64) -> Option<String> {
        self.inode_to_path.read().unwrap().get(&ino).cloned()
    }

    fn is_dir(&self, path: &str) -> bool {
        if path == "/" {
            return true;
        }
        let prefix = if path.ends_with('/') {
            path.to_string()
        } else {
            format!("{path}/")
        };
        let files = self.files.read().unwrap();
        files.keys().any(|k| k.starts_with(&prefix))
    }

    fn file_attr(&self, ino: u64, path: &str) -> FileAttr {
        let files = self.files.read().unwrap();
        if let Some(f) = files.get(path) {
            FileAttr {
                ino,
                size: f.content.len() as u64,
                blocks: (f.content.len() as u64).div_ceil(BLOCK_SIZE as u64),
                atime: f.modified_at,
                mtime: f.modified_at,
                ctime: f.created_at,
                crtime: f.created_at,
                kind: FileType::RegularFile,
                perm: if self.read_write { 0o644 } else { 0o444 },
                nlink: 1,
                uid: 0,
                gid: 0,
                rdev: 0,
                blksize: BLOCK_SIZE,
                flags: 0,
            }
        } else {
            let now = SystemTime::now();
            FileAttr {
                ino,
                size: 0,
                blocks: 0,
                atime: now,
                mtime: now,
                ctime: now,
                crtime: now,
                kind: FileType::Directory,
                perm: if self.read_write { 0o755 } else { 0o555 },
                nlink: 2,
                uid: 0,
                gid: 0,
                rdev: 0,
                blksize: BLOCK_SIZE,
                flags: 0,
            }
        }
    }

    fn dir_entries(&self, dir_path: &str) -> Vec<(String, bool)> {
        let prefix = if dir_path == "/" {
            "/".to_string()
        } else if dir_path.ends_with('/') {
            dir_path.to_string()
        } else {
            format!("{dir_path}/")
        };

        let files = self.files.read().unwrap();
        let mut entries = Vec::new();
        let mut seen_dirs = std::collections::HashSet::new();

        for key in files.keys() {
            if !key.starts_with(&prefix) || key == &prefix {
                continue;
            }
            let rel = &key[prefix.len()..];
            if let Some(slash_pos) = rel.find('/') {
                let subdir = &rel[..slash_pos];
                if seen_dirs.insert(subdir.to_string()) {
                    entries.push((subdir.to_string(), true));
                }
            } else {
                entries.push((rel.to_string(), false));
            }
        }
        entries
    }
}

impl Filesystem for MemoryFuseFs {
    fn lookup(&mut self, _req: &Request, parent: u64, name: &OsStr, reply: ReplyEntry) {
        let name_str = name.to_str().unwrap_or("");
        let parent_path = match self.get_path(parent) {
            Some(p) => p,
            None => {
                reply.error(libc::ENOENT);
                return;
            }
        };

        let child_path = if parent_path == "/" {
            format!("/{name_str}")
        } else {
            format!("{parent_path}/{name_str}")
        };

        let is_file = self.files.read().unwrap().contains_key(&child_path);
        if is_file || self.is_dir(&child_path) {
            let ino = self.get_or_create_inode(&child_path);
            let attr = self.file_attr(ino, &child_path);
            reply.entry(&TTL, &attr, 0);
        } else {
            reply.error(libc::ENOENT);
        }
    }

    fn getattr(&mut self, _req: &Request, ino: u64, _fh: Option<u64>, reply: ReplyAttr) {
        if ino == ROOT_INODE {
            let attr = self.file_attr(ROOT_INODE, "/");
            reply.attr(&TTL, &attr);
            return;
        }
        match self.get_path(ino) {
            Some(path) => {
                let attr = self.file_attr(ino, &path);
                reply.attr(&TTL, &attr);
            }
            None => reply.error(libc::ENOENT),
        }
    }

    fn readdir(
        &mut self,
        _req: &Request,
        ino: u64,
        _fh: u64,
        offset: i64,
        mut reply: ReplyDirectory,
    ) {
        let dir_path = if ino == ROOT_INODE {
            "/".to_string()
        } else {
            match self.get_path(ino) {
                Some(p) => p,
                None => {
                    reply.error(libc::ENOENT);
                    return;
                }
            }
        };

        let mut entries: Vec<(u64, FileType, String)> = vec![
            (ino, FileType::Directory, ".".to_string()),
            (ino, FileType::Directory, "..".to_string()),
        ];

        for (name, is_dir) in self.dir_entries(&dir_path) {
            let child_path = if dir_path == "/" {
                format!("/{name}")
            } else {
                format!("{dir_path}/{name}")
            };
            let child_ino = self.get_or_create_inode(&child_path);
            let ft = if is_dir {
                FileType::Directory
            } else {
                FileType::RegularFile
            };
            entries.push((child_ino, ft, name));
        }

        for (i, (ino, ft, name)) in entries.iter().enumerate().skip(offset as usize) {
            if reply.add(*ino, (i + 1) as i64, *ft, name) {
                break;
            }
        }
        reply.ok();
    }

    fn read(
        &mut self,
        _req: &Request,
        ino: u64,
        _fh: u64,
        offset: i64,
        size: u32,
        _flags: i32,
        _lock_owner: Option<u64>,
        reply: ReplyData,
    ) {
        let path = match self.get_path(ino) {
            Some(p) => p,
            None => {
                reply.error(libc::ENOENT);
                return;
            }
        };
        let files = self.files.read().unwrap();
        match files.get(&path) {
            Some(f) => {
                let start = offset as usize;
                if start >= f.content.len() {
                    reply.data(&[]);
                } else {
                    let end = (start + size as usize).min(f.content.len());
                    reply.data(&f.content[start..end]);
                }
            }
            None => reply.error(libc::ENOENT),
        }
    }

    fn write(
        &mut self,
        _req: &Request,
        ino: u64,
        _fh: u64,
        offset: i64,
        data: &[u8],
        _write_flags: u32,
        _flags: i32,
        _lock_owner: Option<u64>,
        reply: ReplyWrite,
    ) {
        if !self.read_write {
            reply.error(libc::EACCES);
            return;
        }
        let path = match self.get_path(ino) {
            Some(p) => p,
            None => {
                reply.error(libc::ENOENT);
                return;
            }
        };
        let mut files = self.files.write().unwrap();
        let file = files.entry(path.clone()).or_insert_with(|| InMemoryFile {
            content: Vec::new(),
            created_at: SystemTime::now(),
            modified_at: SystemTime::now(),
        });
        let offset = offset as usize;
        if offset + data.len() > file.content.len() {
            file.content.resize(offset + data.len(), 0);
        }
        file.content[offset..offset + data.len()].copy_from_slice(data);
        file.modified_at = SystemTime::now();
        let content = file.content.clone();
        drop(files);

        let _ = self.sync_tx.send(SyncRequest {
            mount_name: self.mount_name.clone(),
            relative_path: path,
            content,
            operation: "write".to_string(),
        });

        reply.written(data.len() as u32);
    }

    fn create(
        &mut self,
        _req: &Request,
        parent: u64,
        name: &OsStr,
        _mode: u32,
        _umask: u32,
        _flags: i32,
        reply: ReplyCreate,
    ) {
        if !self.read_write {
            reply.error(libc::EACCES);
            return;
        }
        let name_str = name.to_str().unwrap_or("");
        let parent_path = match self.get_path(parent) {
            Some(p) => p,
            None => {
                reply.error(libc::ENOENT);
                return;
            }
        };
        let child_path = if parent_path == "/" {
            format!("/{name_str}")
        } else {
            format!("{parent_path}/{name_str}")
        };

        let now = SystemTime::now();
        self.files.write().unwrap().insert(
            child_path.clone(),
            InMemoryFile {
                content: Vec::new(),
                created_at: now,
                modified_at: now,
            },
        );

        let ino = self.get_or_create_inode(&child_path);
        let attr = self.file_attr(ino, &child_path);

        let _ = self.sync_tx.send(SyncRequest {
            mount_name: self.mount_name.clone(),
            relative_path: child_path,
            content: Vec::new(),
            operation: "write".to_string(),
        });

        reply.created(&TTL, &attr, 0, 0, 0);
    }

    fn unlink(&mut self, _req: &Request, parent: u64, name: &OsStr, reply: ReplyEmpty) {
        if !self.read_write {
            reply.error(libc::EACCES);
            return;
        }
        let name_str = name.to_str().unwrap_or("");
        let parent_path = match self.get_path(parent) {
            Some(p) => p,
            None => {
                reply.error(libc::ENOENT);
                return;
            }
        };
        let child_path = if parent_path == "/" {
            format!("/{name_str}")
        } else {
            format!("{parent_path}/{name_str}")
        };

        if self.files.write().unwrap().remove(&child_path).is_some() {
            if let Some(ino) = self.path_to_inode.write().unwrap().remove(&child_path) {
                self.inode_to_path.write().unwrap().remove(&ino);
            }
            let _ = self.sync_tx.send(SyncRequest {
                mount_name: self.mount_name.clone(),
                relative_path: child_path,
                content: Vec::new(),
                operation: "delete".to_string(),
            });
            reply.ok();
        } else {
            reply.error(libc::ENOENT);
        }
    }

    fn mkdir(
        &mut self,
        _req: &Request,
        parent: u64,
        name: &OsStr,
        _mode: u32,
        _umask: u32,
        reply: ReplyEntry,
    ) {
        if !self.read_write {
            reply.error(libc::EACCES);
            return;
        }
        let name_str = name.to_str().unwrap_or("");
        let parent_path = match self.get_path(parent) {
            Some(p) => p,
            None => {
                reply.error(libc::ENOENT);
                return;
            }
        };
        let child_path = if parent_path == "/" {
            format!("/{name_str}")
        } else {
            format!("{parent_path}/{name_str}")
        };

        let ino = self.get_or_create_inode(&child_path);
        let attr = self.file_attr(ino, &child_path);
        reply.entry(&TTL, &attr, 0);
    }

    fn rmdir(&mut self, _req: &Request, parent: u64, name: &OsStr, reply: ReplyEmpty) {
        if !self.read_write {
            reply.error(libc::EACCES);
            return;
        }
        let name_str = name.to_str().unwrap_or("");
        let parent_path = match self.get_path(parent) {
            Some(p) => p,
            None => {
                reply.error(libc::ENOENT);
                return;
            }
        };
        let child_path = if parent_path == "/" {
            format!("/{name_str}")
        } else {
            format!("{parent_path}/{name_str}")
        };

        if self.dir_entries(&child_path).is_empty() {
            if let Some(ino) = self.path_to_inode.write().unwrap().remove(&child_path) {
                self.inode_to_path.write().unwrap().remove(&ino);
            }
            reply.ok();
        } else {
            reply.error(libc::ENOTEMPTY);
        }
    }

    fn setattr(
        &mut self,
        _req: &Request,
        ino: u64,
        _mode: Option<u32>,
        _uid: Option<u32>,
        _gid: Option<u32>,
        size: Option<u64>,
        _atime: Option<fuser::TimeOrNow>,
        _mtime: Option<fuser::TimeOrNow>,
        _ctime: Option<SystemTime>,
        _fh: Option<u64>,
        _crtime: Option<SystemTime>,
        _chgtime: Option<SystemTime>,
        _bkuptime: Option<SystemTime>,
        _flags: Option<u32>,
        reply: ReplyAttr,
    ) {
        let path = match self.get_path(ino) {
            Some(p) => p,
            None => {
                reply.error(libc::ENOENT);
                return;
            }
        };

        if let Some(new_size) = size {
            if !self.read_write {
                reply.error(libc::EACCES);
                return;
            }
            let mut files = self.files.write().unwrap();
            if let Some(f) = files.get_mut(&path) {
                f.content.truncate(new_size as usize);
                if (new_size as usize) > f.content.len() {
                    f.content.resize(new_size as usize, 0);
                }
                f.modified_at = SystemTime::now();
                let content = f.content.clone();
                drop(files);
                let _ = self.sync_tx.send(SyncRequest {
                    mount_name: self.mount_name.clone(),
                    relative_path: path.clone(),
                    content,
                    operation: "write".to_string(),
                });
            }
        }

        let attr = self.file_attr(ino, &path);
        reply.attr(&TTL, &attr);
    }

    fn rename(
        &mut self,
        _req: &Request,
        parent: u64,
        name: &OsStr,
        newparent: u64,
        newname: &OsStr,
        _flags: u32,
        reply: ReplyEmpty,
    ) {
        if !self.read_write {
            reply.error(libc::EACCES);
            return;
        }
        let name_str = name.to_str().unwrap_or("");
        let newname_str = newname.to_str().unwrap_or("");

        let parent_path = match self.get_path(parent) {
            Some(p) => p,
            None => {
                reply.error(libc::ENOENT);
                return;
            }
        };
        let newparent_path = match self.get_path(newparent) {
            Some(p) => p,
            None => {
                reply.error(libc::ENOENT);
                return;
            }
        };

        let old_path = if parent_path == "/" {
            format!("/{name_str}")
        } else {
            format!("{parent_path}/{name_str}")
        };
        let new_path = if newparent_path == "/" {
            format!("/{newname_str}")
        } else {
            format!("{newparent_path}/{newname_str}")
        };

        let mut files = self.files.write().unwrap();
        if let Some(file) = files.remove(&old_path) {
            let content = file.content.clone();
            files.insert(new_path.clone(), file);
            drop(files);

            if let Some(ino) = self.path_to_inode.write().unwrap().remove(&old_path) {
                self.inode_to_path.write().unwrap().remove(&ino);
                self.path_to_inode
                    .write()
                    .unwrap()
                    .insert(new_path.clone(), ino);
                self.inode_to_path
                    .write()
                    .unwrap()
                    .insert(ino, new_path.clone());
            }

            let _ = self.sync_tx.send(SyncRequest {
                mount_name: self.mount_name.clone(),
                relative_path: old_path,
                content: Vec::new(),
                operation: "delete".to_string(),
            });
            let _ = self.sync_tx.send(SyncRequest {
                mount_name: self.mount_name.clone(),
                relative_path: new_path,
                content,
                operation: "write".to_string(),
            });
            reply.ok();
        } else {
            reply.error(libc::ENOENT);
        }
    }
}

struct FuseStoreRef {
    files: Arc<RwLock<HashMap<String, InMemoryFile>>>,
    inode_to_path: Arc<RwLock<HashMap<u64, String>>>,
    path_to_inode: Arc<RwLock<HashMap<String, u64>>>,
    next_inode: Arc<AtomicU64>,
}

pub struct MemoryFuseHandle {
    _sessions: Vec<fuser::BackgroundSession>,
    stores: HashMap<String, FuseStoreRef>,
}

impl MemoryFuseHandle {
    pub fn mount_all(
        mounts: &[proto::MemoryStoreMount],
        runner_tx: mpsc::Sender<RunnerMessage>,
    ) -> Result<Self, anyhow::Error> {
        let mut sessions = Vec::new();
        let mut stores = HashMap::new();

        for mount in mounts {
            if mount.files.is_empty() && mount.mount_name.is_empty() {
                continue;
            }

            let mount_path = PathBuf::from(&mount.mount_path);
            std::fs::create_dir_all(&mount_path)?;

            let read_write = mount.access != "read_only";
            let now = SystemTime::now();

            let mut files = HashMap::new();
            let mut path_to_inode = HashMap::new();
            let mut inode_to_path = HashMap::new();
            let mut next_inode_val: u64 = 2;

            path_to_inode.insert("/".to_string(), ROOT_INODE);
            inode_to_path.insert(ROOT_INODE, "/".to_string());

            for f in &mount.files {
                files.insert(
                    f.relative_path.clone(),
                    InMemoryFile {
                        content: f.content.clone(),
                        created_at: now,
                        modified_at: now,
                    },
                );

                let parts: Vec<&str> = f
                    .relative_path
                    .split('/')
                    .filter(|s| !s.is_empty())
                    .collect();
                let mut prefix = String::new();
                for (i, part) in parts.iter().enumerate() {
                    prefix = format!("{prefix}/{part}");
                    if !path_to_inode.contains_key(&prefix) {
                        path_to_inode.insert(prefix.clone(), next_inode_val);
                        inode_to_path.insert(next_inode_val, prefix.clone());
                        next_inode_val += 1;
                    }
                    let _ = i;
                }
            }

            let (sync_tx, sync_rx) = std::sync::mpsc::channel::<SyncRequest>();

            let files_arc = Arc::new(RwLock::new(files));
            let inode_to_path_arc = Arc::new(RwLock::new(inode_to_path));
            let path_to_inode_arc = Arc::new(RwLock::new(path_to_inode));
            let next_inode_arc = Arc::new(AtomicU64::new(next_inode_val));

            stores.insert(
                mount.mount_name.clone(),
                FuseStoreRef {
                    files: files_arc.clone(),
                    inode_to_path: inode_to_path_arc.clone(),
                    path_to_inode: path_to_inode_arc.clone(),
                    next_inode: next_inode_arc.clone(),
                },
            );

            let fs = MemoryFuseFs {
                read_write,
                mount_name: mount.mount_name.clone(),
                files: files_arc,
                inode_to_path: inode_to_path_arc,
                path_to_inode: path_to_inode_arc,
                next_inode: next_inode_arc,
                sync_tx,
            };

            let options = vec![
                MountOption::FSName("joysafeter-memory".into()),
                MountOption::AutoUnmount,
                MountOption::AllowOther,
            ];

            let session = fuser::spawn_mount2(fs, &mount_path, &options)
                .map_err(|e| anyhow::anyhow!("FUSE mount at {} failed: {}", mount.mount_path, e))?;

            info!(
                mount_path = %mount.mount_path,
                mount_name = %mount.mount_name,
                files = mount.files.len(),
                access = %mount.access,
                "FUSE memory store mounted"
            );

            sessions.push(session);

            let tx = runner_tx.clone();
            let mount_name = mount.mount_name.clone();
            std::thread::spawn(move || {
                while let Ok(req) = sync_rx.recv() {
                    let msg = RunnerMessage {
                        payload: Some(proto::runner_message::Payload::MemorySync(
                            proto::MemoryFileSync {
                                store_mount_name: req.mount_name,
                                relative_path: req.relative_path,
                                content: String::from_utf8_lossy(&req.content).to_string(),
                                operation: req.operation,
                            },
                        )),
                    };
                    if tx.blocking_send(msg).is_err() {
                        warn!(mount_name = %mount_name, "Failed to send MemoryFileSync, channel closed");
                        break;
                    }
                }
            });
        }

        Ok(MemoryFuseHandle {
            _sessions: sessions,
            stores,
        })
    }

    /// Write (or overwrite) a file in the FUSE in-memory store from an external sync event.
    pub fn write_file(&self, mount_name: &str, relative_path: &str, content: &[u8]) {
        let Some(store) = self.stores.get(mount_name) else {
            return;
        };
        let now = SystemTime::now();
        let mut files = store.files.write().unwrap();
        files.insert(
            relative_path.to_string(),
            InMemoryFile {
                content: content.to_vec(),
                created_at: now,
                modified_at: now,
            },
        );
        drop(files);

        // Ensure inode exists for the path and parent directories
        let parts: Vec<&str> = relative_path.split('/').filter(|s| !s.is_empty()).collect();
        let mut p2i = store.path_to_inode.write().unwrap();
        let mut i2p = store.inode_to_path.write().unwrap();
        let mut prefix = String::new();
        for part in &parts {
            prefix = format!("{prefix}/{part}");
            if !p2i.contains_key(&prefix) {
                let ino = store.next_inode.fetch_add(1, Ordering::SeqCst);
                p2i.insert(prefix.clone(), ino);
                i2p.insert(ino, prefix.clone());
            }
        }
    }

    /// Remove a file from the FUSE in-memory store due to an external sync event.
    pub fn remove_file(&self, mount_name: &str, relative_path: &str) {
        let Some(store) = self.stores.get(mount_name) else {
            return;
        };
        let mut files = store.files.write().unwrap();
        files.remove(relative_path);
    }
}
