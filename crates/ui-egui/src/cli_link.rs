//! `solidcraft-cli` on PATH for a macOS app bundle (a DMG install has no installer step): a
//! symlink in `/opt/homebrew/bin` or `/usr/local/bin` to the CLI inside the bundle, made quietly at
//! launch when one of them is writable, or from Help > Install solidcraft-cli command, which asks
//! for an administrator password when it must. A file that is not our symlink is never replaced.

use std::path::{Path, PathBuf};

/// Find the external MCP CLI without loading the embedded assistant implementation.
#[cfg(not(target_arch = "wasm32"))]
pub fn find_cli() -> Option<PathBuf> {
    let name = if cfg!(windows) { "solidcraft-cli.exe" } else { "solidcraft-cli" };
    if let Some(path) = solidcraft_engine::geom::env::var("CLI").map(PathBuf::from).filter(|path| path.is_file()) {
        return Some(path);
    }
    std::env::current_exe().ok().and_then(|exe| exe.parent().map(|directory| directory.join(name))).filter(|path| path.is_file()).or_else(|| {
        let names = if cfg!(windows) { vec!["solidcraft-cli.exe", "solidcraft-cli.cmd", "solidcraft-cli.bat"] } else { vec!["solidcraft-cli"] };
        search_dirs().iter().flat_map(|directory| names.iter().map(move |name| directory.join(name))).find(|path| path.is_file())
    })
}

/// PATH, then the usual places npm, Homebrew, nvm, Volta, bun, pipx and Grok put commands, and on
/// Windows Node's own install folders: a launcher can start SolidCraft with a PATH that lacks
/// them, and an npm agent's `.cmd` shim then can't find `node` (#9297).
pub fn search_dirs() -> Vec<PathBuf> {
    search_dirs_in(&|name| std::env::var_os(name), cfg!(windows))
}

/// [`search_dirs`] in the environment `var` reads, on Windows or not.
pub(crate) fn search_dirs_in(var: &dyn Fn(&str) -> Option<std::ffi::OsString>, windows: bool) -> Vec<PathBuf> {
    let mut dirs: Vec<PathBuf> = var("PATH").map(|p| std::env::split_paths(&p).collect()).unwrap_or_default();
    if let Some(prefix) = var("NPM_CONFIG_PREFIX").map(PathBuf::from) {
        dirs.push(if windows { prefix.clone() } else { prefix.join("bin") });
    }
    if let Some(h) = var(if windows { "USERPROFILE" } else { "HOME" }).map(PathBuf::from).filter(|p| p.is_absolute()) {
        for d in [".local/bin", ".npm-global/bin", ".npm-packages/bin", ".volta/bin", ".bun/bin", ".cargo/bin", ".grok/bin", "bin"] {
            dirs.push(h.join(d));
        }
        // nvm: every installed Node version's bin.
        if let Ok(rd) = std::fs::read_dir(h.join(".nvm/versions/node")) {
            let mut v: Vec<PathBuf> = rd.flatten().take(64).map(|e| e.path().join("bin")).collect();
            v.sort();
            dirs.extend(v.into_iter().rev());
        }
    }
    if windows {
        if let Some(a) = var("APPDATA") {
            dirs.push(PathBuf::from(a).join("npm"));
        }
        // Node's installers (64-bit and 32-bit), and nvm-windows' link to the version in use.
        for program_files in ["ProgramFiles", "ProgramFiles(x86)"] {
            dirs.extend(var(program_files).map(|d| PathBuf::from(d).join("nodejs")));
        }
        dirs.extend(var("NVM_SYMLINK").map(PathBuf::from));
    } else {
        for d in ["/opt/homebrew/bin", "/usr/local/bin", "/home/linuxbrew/.linuxbrew/bin", "/usr/bin"] {
            dirs.push(PathBuf::from(d));
        }
    }
    let mut seen = std::collections::HashSet::new();
    dirs.retain(|d| d.is_absolute() && seen.insert(d.clone()));
    dirs
}

/// What a link's place holds now.
#[derive(Debug, PartialEq)]
pub enum Slot {
    Empty,
    /// A symbolic link, to this path.
    Link(PathBuf),
    /// A file, a folder, or anything else: the user's.
    Other,
}

#[derive(Debug, PartialEq)]
pub enum Plan {
    /// The link is already right.
    Keep,
    /// Make it, or replace a stale link of ours.
    Write,
    /// Leave it: something else is there.
    Skip,
}

/// Whether `target` is a CLI inside some SolidCraft app bundle (an older or moved bundle's link
/// is ours to refresh).
fn ours(target: &Path) -> bool {
    let s = target.to_string_lossy();
    s.ends_with(".app/Contents/MacOS/solidcraft-cli")
}

/// What to do about the link slot for the CLI at `cli`.
pub fn plan(slot: &Slot, cli: &Path) -> Plan {
    match slot {
        Slot::Empty => Plan::Write,
        Slot::Link(t) if t == cli => Plan::Keep,
        Slot::Link(t) if ours(t) => Plan::Write,
        _ => Plan::Skip,
    }
}

/// The folders a link goes in, best first.
pub const DIRS: &[&str] = &["/opt/homebrew/bin", "/usr/local/bin"];

#[cfg(unix)]
fn slot(link: &Path) -> Slot {
    match std::fs::symlink_metadata(link) {
        Err(_) => Slot::Empty,
        Ok(m) if m.file_type().is_symlink() => std::fs::read_link(link).map_or(Slot::Other, Slot::Link),
        Ok(_) => Slot::Other,
    }
}

/// The CLI beside the running app, when the app runs from a bundle.
fn bundled_cli() -> Option<PathBuf> {
    let cli = std::env::current_exe().ok()?.parent()?.join("solidcraft-cli");
    (cli.is_file() && ours(&cli)).then_some(cli)
}

fn on_path_elsewhere(path_var: &std::ffi::OsStr, dirs: &[&str]) -> bool {
    std::env::split_paths(path_var).any(|d| !dirs.iter().any(|x| Path::new(x) == d) && d.join("solidcraft-cli").exists())
}

/// Make the link in `dirs` (the first that takes it). Returns the link made or kept.
#[cfg(unix)]
fn link_in(dirs: &[&str], cli: &Path) -> Option<PathBuf> {
    for dir in dirs {
        let link = Path::new(dir).join("solidcraft-cli");
        match plan(&slot(&link), cli) {
            Plan::Keep => return Some(link),
            Plan::Skip => continue,
            Plan::Write => {
                if !Path::new(dir).is_dir() {
                    continue;
                }
                let _ = std::fs::remove_file(&link);
                if std::os::unix::fs::symlink(cli, &link).is_ok() {
                    return Some(link);
                }
            }
        }
    }
    None
}

#[cfg(not(unix))]
fn link_in(_dirs: &[&str], _cli: &Path) -> Option<PathBuf> {
    None
}

/// At launch: best effort, silent. Does nothing off macOS, outside a bundle, or when
/// `solidcraft-cli` is already on PATH from somewhere else.
pub fn install_on_launch() {
    if !cfg!(target_os = "macos") {
        return;
    }
    let Some(cli) = bundled_cli() else { return };
    if std::env::var_os("PATH").is_some_and(|p| on_path_elsewhere(&p, DIRS)) {
        return;
    }
    link_in(DIRS, &cli);
}

/// Help > Install solidcraft-cli command: the same, then with an administrator prompt into
/// `/usr/local/bin` when no folder is writable. A message for the status line, and whether it failed.
pub fn install_from_menu() -> (String, bool) {
    if !cfg!(target_os = "macos") {
        return ("This is for the macOS app; the other packages put solidcraft-cli on PATH themselves.".into(), true);
    }
    let Some(cli) = bundled_cli() else {
        return ("solidcraft-cli was not found inside this app.".into(), true);
    };
    if let Some(l) = link_in(DIRS, &cli) {
        return (format!("solidcraft-cli is available as {}", l.display()), false);
    }
    let Some(script) = admin_script(&cli) else {
        return ("The app's path has characters the installer cannot quote; move SolidCraft to /Applications.".into(), true);
    };
    match std::process::Command::new("osascript").args(["-e", &script]).output() {
        Ok(o) if o.status.success() => ("solidcraft-cli is available as /usr/local/bin/solidcraft-cli".into(), false),
        Ok(o) => (format!("Not installed: {}", String::from_utf8_lossy(&o.stderr).trim()), true),
        Err(e) => (format!("Not installed: {e}"), true),
    }
}

/// The AppleScript that links `cli` into `/usr/local/bin` as an administrator. None when the path
/// holds a character that would need escaping (a quote or backslash), or an existing file is there.
pub fn admin_script(cli: &Path) -> Option<String> {
    let c = cli.to_str()?;
    if c.contains(['\'', '"', '\\', '\n']) {
        return None;
    }
    // `[ -e ] && ! [ -L ]`: never replace a file that is not a link.
    Some(format!(
        "do shell script \"mkdir -p /usr/local/bin && if [ -e /usr/local/bin/solidcraft-cli ] && [ ! -L /usr/local/bin/solidcraft-cli ]; then echo 'a file named solidcraft-cli is already in /usr/local/bin' >&2; exit 1; fi && ln -sfn '{c}' /usr/local/bin/solidcraft-cli\" with administrator privileges"
    ))
}

#[cfg(test)]
mod tests {
    use super::*;

    const CLI: &str = "/Applications/SolidCraft.app/Contents/MacOS/solidcraft-cli";

    #[test]
    fn external_cli_search_keeps_path_priority_and_ignores_relative_duplicates() {
        let first = std::env::temp_dir().join("faber-cli-path-first");
        let path = std::env::join_paths([first.as_path(), Path::new("relative"), first.as_path()]).unwrap();
        let dirs = search_dirs_in(&|name| (name == "PATH").then(|| path.clone()), true);
        assert_eq!(dirs, [first]);
    }

    #[test]
    fn external_cli_override_does_not_need_the_chat_module() {
        const CHILD: &str = "FABER_CLI_LOOKUP_TEST_CHILD";
        if let Some(expected) = std::env::var_os(CHILD) {
            assert_eq!(find_cli(), Some(PathBuf::from(expected)));
            return;
        }
        let nonce = std::time::SystemTime::now().duration_since(std::time::UNIX_EPOCH).unwrap().as_nanos();
        let directory = std::env::temp_dir().join(format!("faber-cli-lookup-{}-{nonce}", std::process::id()));
        std::fs::create_dir(&directory).unwrap();
        let candidate = directory.join(if cfg!(windows) { "solidcraft-cli.exe" } else { "solidcraft-cli" });
        std::fs::write(&candidate, "lookup only; never executed").unwrap();
        let result = std::process::Command::new(std::env::current_exe().unwrap())
            .args(["--exact", "cli_link::tests::external_cli_override_does_not_need_the_chat_module"])
            .env(CHILD, &candidate)
            .env("CLI", &candidate)
            .output()
            .unwrap();
        std::fs::remove_file(candidate).unwrap();
        std::fs::remove_dir(directory).unwrap();
        assert!(result.status.success(), "{}", String::from_utf8_lossy(&result.stdout));
    }

    #[test]
    fn plans() {
        let cli = Path::new(CLI);
        assert_eq!(plan(&Slot::Empty, cli), Plan::Write);
        assert_eq!(plan(&Slot::Link(cli.into()), cli), Plan::Keep);
        // A link to a moved or older bundle is ours to refresh; to anything else, not.
        assert_eq!(plan(&Slot::Link("/Users/me/Old.app/Contents/MacOS/solidcraft-cli".into()), cli), Plan::Write);
        assert_eq!(plan(&Slot::Link("/opt/other/solidcraft-cli".into()), cli), Plan::Skip);
        assert_eq!(plan(&Slot::Other, cli), Plan::Skip);
    }

    // `link_in` only makes links on Unix, and the test makes its own with `std::os::unix`.
    #[cfg(unix)]
    #[test]
    #[cfg(unix)]
    fn links_only_where_it_may() {
        let d = std::env::temp_dir().join(format!("solidcraft-cli-link-{}", std::process::id()));
        let _ = std::fs::remove_dir_all(&d);
        let (a, b) = (d.join("a"), d.join("b"));
        std::fs::create_dir_all(&a).unwrap();
        std::fs::create_dir_all(&b).unwrap();
        let cli = Path::new(CLI);
        let dirs = [a.to_str().unwrap(), b.to_str().unwrap()];
        // A file of the user's blocks its folder; the next one gets the link.
        std::fs::write(a.join("solidcraft-cli"), "mine").unwrap();
        assert_eq!(link_in(&dirs, cli), Some(b.join("solidcraft-cli")));
        assert_eq!(std::fs::read_to_string(a.join("solidcraft-cli")).unwrap(), "mine");
        assert_eq!(std::fs::read_link(b.join("solidcraft-cli")).unwrap(), cli);
        // A stale link of ours is refreshed.
        std::fs::remove_file(b.join("solidcraft-cli")).unwrap();
        std::os::unix::fs::symlink("/x/Old.app/Contents/MacOS/solidcraft-cli", b.join("solidcraft-cli")).unwrap();
        assert_eq!(link_in(&dirs[1..], cli), Some(b.join("solidcraft-cli")));
        assert_eq!(std::fs::read_link(b.join("solidcraft-cli")).unwrap(), cli);
        let _ = std::fs::remove_dir_all(&d);
    }

    #[test]
    fn path_check_ignores_our_own_folders() {
        let d = std::env::temp_dir().join(format!("solidcraft-cli-path-{}", std::process::id()));
        std::fs::create_dir_all(&d).unwrap();
        std::fs::write(d.join("solidcraft-cli"), "").unwrap();
        let path = std::env::join_paths([d.as_path()]).unwrap();
        assert!(on_path_elsewhere(&path, &["/opt/homebrew/bin"]));
        assert!(!on_path_elsewhere(&path, &[d.to_str().unwrap()]));
        let _ = std::fs::remove_dir_all(&d);
    }

    #[test]
    fn admin_script_refuses_paths_that_need_escaping() {
        assert!(admin_script(Path::new(CLI)).unwrap().contains("with administrator privileges"));
        assert!(admin_script(Path::new("/Apps/It's.app/Contents/MacOS/solidcraft-cli")).is_none());
        assert!(admin_script(Path::new("/Apps/a\"b.app/Contents/MacOS/solidcraft-cli")).is_none());
    }
}
