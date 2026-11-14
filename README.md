# GitHub Release Downloader Py

An interactive Python utility for downloading GitHub Release assets from one or more repositories. It supports Stable and Pre-release channels, direct release-tag URLs, filename filters, parallel downloads, resumable transfers, optional GitHub authentication, and diagnostic logging.

**Python implementation:** `github_release_downloader.py`  
**Dependencies:** Python standard library only. `aria2` is not required.

## Features

- Download the newest published **Stable** release or newest published **Pre-release** for configured repositories.
- Download one specific release by pasting its GitHub tag URL.
- Select multiple repositories with number lists and ranges (for example `1, 2, 5-8`), select all, or remove selected entries.
- Configure repositories and their release channels in the `REPOSITORIES` list near the top of the Python file.
- Optional case-insensitive filename exclusion and include-only keyword filters.
- Independently include or exclude `.msi`, source ZIP, and repository `README.md` downloads.
- Download several files concurrently per repository; repositories are processed sequentially.
- Stream large files to disk instead of loading them into memory.
- Resume interrupted downloads when the server supports HTTP Range requests. Partial data is kept in `.part` files.
- Automatically use `GH_TOKEN`, `GITHUB_TOKEN`, or an existing GitHub CLI login (`gh auth token`).
- Log run events and failures to `GitHub-Release-Downloader.log`; temporary signed URL query strings and bearer tokens are redacted.
- Three error-handling modes: skip and continue, ask what to do, or automatically retry once and then skip.
- Verify SHA-256 when GitHub provides an asset digest.
- Skip non-empty files already downloaded.

## Requirements

- Python **3.10 or newer** (uses modern standard-library and typing features).
- Internet access to the GitHub API and GitHub release download hosts.
- No third-party Python packages are required.

## Quick start

1. Download or clone this repository.
2. Open a terminal in the project folder.
3. Run:

   ```bash
   python github_release_downloader.py
   ```

On Windows, `py github_release_downloader.py` also works when the Python launcher is installed.

## Configuration

Open `github_release_downloader.py` and edit the `REPOSITORIES` list:

```python
REPOSITORIES = [
    {"owner": "octocat", "name": "Hello-World", "channel": "Stable"},
    {"owner": "some-project", "name": "another-project", "channel": "Pre-release"},
]
```

- `owner`: GitHub account or organization.
- `name`: repository name.
- `channel`: `Stable` or `Pre-release`.

You can add, edit, or remove entries. The `DEFAULT_EXCLUSIONS`, `DEFAULT_MAX_WORKERS`, `DEFAULT_RETRIES`, and `DEFAULT_ERROR_MODE` values can also be changed near the top of the script.

### GitHub authentication (optional)

Public repositories can be accessed without authentication, but GitHub applies lower API rate limits. Authentication is detected in this order:

1. `GH_TOKEN` environment variable.
2. `GITHUB_TOKEN` environment variable.
3. Existing GitHub CLI login (`gh auth token --hostname github.com`).

For example, in PowerShell:

```powershell
$env:GH_TOKEN = "YOUR_GITHUB_TOKEN"
python .\github_release_downloader.py
```

In Bash:

```bash
export GH_TOKEN="YOUR_GITHUB_TOKEN"
python3 github_release_downloader.py
```

Use a token with only the permissions needed for the repositories you access. Do not paste tokens into source files or share log files containing private information.

## Interactive workflow

1. Choose configured repositories or provide a specific GitHub release URL.
2. Optionally enable advanced filters and download restrictions.
3. Choose the maximum number of simultaneous file downloads per repository.
4. Choose an error-handling mode.
5. Review the download plan and confirm.

Specific release URL format:

```text
https://github.com/OWNER/REPOSITORY/releases/tag/TAG
```

## Error handling

Choose one of the following at startup:

| Mode | Behavior |
|---|---|
| `1` | Log and notify about a failed file, skip it, and continue. |
| `2` | Stop scheduling new work for the failed batch and ask whether to retry, skip, or stop the remaining run. |
| `3` | Automatically retry a failed download once, then skip it and continue. This is the default. |

Errors are printed to the console and recorded in `GitHub-Release-Downloader.log`. A non-zero process exit code is returned when tasks were skipped after errors or the run was stopped by the user.

## Download location and resume behavior

Each release is saved in a folder beside the script, named:

```text
repository-name-release-tag/
```

Downloads are written to `filename.part` until the transfer completes. The downloader then renames the partial file to its final name. If the process is interrupted, run the program again and select the same repository/release; the `.part` file is used as the starting point when the server honors HTTP Range requests. If a server does not support resuming, the partial file is discarded and the download restarts.

A non-empty final file is treated as already downloaded and skipped. If you suspect that a completed file is corrupt, remove it manually before rerunning. SHA-256 is checked only when GitHub's release asset metadata supplies a digest.

## Troubleshooting

### GitHub API returns 403 or a rate-limit error

Wait until the rate limit resets, or authenticate using `GH_TOKEN`, `GITHUB_TOKEN`, or `gh auth login`. Avoid repeatedly restarting the program while rate-limited.

### No release is found

Check that the repository has a published GitHub Release (a Git tag alone is not necessarily a release). Choose `Pre-release` for projects that publish preview builds and `Stable` for regular releases.

### A download fails or stops

Check the console error and `GitHub-Release-Downloader.log`. Verify free disk space, destination-folder write permissions, network stability, and whether the upstream asset is still available. Retry by running the program again; unfinished `.part` files can be resumed when supported by the server.

### Python version error

Install Python 3.10 or newer and check the version with `python --version` (or `py --version` on Windows).

## Safety and responsible use

- The program reads public GitHub release metadata and downloads files from URLs returned by GitHub. It does not publish releases, modify repositories, or change GitHub account settings.
- Downloaded executables and archives are third-party files. Review the upstream project and verify signatures/checksums where available before running them.
- Downloading a file does not grant redistribution rights. Follow the upstream project's license and terms.
- Use reasonable concurrency and respect GitHub API limits and upstream hosting policies.
- This project is not affiliated with, endorsed by, or sponsored by GitHub.

## Credits
The code was written using web version of ChatGPT ??.

## License

[MIT](LICENSE)
