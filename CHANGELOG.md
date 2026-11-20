# Changelog

## [1.3.5] - Per-file sizes and downloaded-data summaries

### Added

- Display the expected size of every file in its progress row, including compact terminal layouts. If the size is unavailable, explicitly show `Size unknown` together with the amount transferred so far.
- Display the total size of successfully downloaded files after each release.
- Display the combined size of successfully downloaded files across all releases in the final session summary.
- Read the repository README size from GitHub metadata when available.

### Changed

- Calculate release and session download-volume summaries from the actual sizes of successfully saved files. Files that already existed and were skipped are not counted.
- Updated the application User-Agent version to 1.3.5.

## [1.3.4] - Windows console compatibility and adaptive progress layout

### Fixed

- Added automatic Windows Virtual Terminal Processing detection and enablement through the Windows console API, preventing ANSI escape sequences from being printed literally in supported classic consoles.
- Added a plain-text progress fallback when VT processing cannot be enabled or the output is not an interactive terminal.
- Made progress rows more compact on narrower terminal windows to reduce line wrapping and cursor-positioning issues.

### Changed

- Updated the application User-Agent version to 1.3.4.
- Updated README terminal compatibility and progress-display documentation.

## [1.3.3] - Separate working indicator from file rows

### Fixed

- Moved the animated `Working` activity indicator to its own status line above the file list.
- Replaced the inline working animation on files with unknown sizes with a neutral progress bar, preventing it from overlapping or obscuring filenames such as `source-code.zip` and `README.md`.

### Changed

- Updated the application User-Agent version to 1.3.3.

## [1.3.2] - Stable completed-file transfer speed

### Fixed

- Freeze the displayed transfer speed when a file finishes downloading, so completed files retain their final speed while other downloads continue.

### Changed

- Updated the application User-Agent version to 1.3.2.

## [1.3.1] - Active filter summary and English documentation

### Added

- Print the exact filename filters active for the current run before downloads begin.
- Include configured exclusion fragments, include-only keywords, and the `.msi` exclusion in the filter summary when those rules are active.
- Explicitly report when no filename filters are active and all release asset filenames are eligible.

### Changed

- Rewrote `README.md` entirely in English.
- Confirmed that all Markdown project documentation (`README.md`, `CHANGELOG.md`, and `GITHUB_RELEASE_DESCRIPTION.md`) is in English.
- Updated the application User-Agent version to 1.3.1.

## [1.3.0] - Interactive exclusion choice and colorized progress

### Added

- Added a startup prompt to apply or skip configured filename exclusion filters for each download session. Its default answer is controlled by `APPLY_DEFAULT_EXCLUSIONS`.
- Added multi-color ANSI progress output using only the Python standard library: progress bars, percentages, transferred bytes, speed, ETA, filenames, and statuses use distinct colors.
- Added the `USE_ANSI_COLORS` setting and support for the standard `NO_COLOR` environment variable.

### Changed

- Updated the README with the exclusion-filter prompt, color behavior, and color-disable instructions.
- Updated the release description and project version to 1.3.0.

### Removed

- Removed `requirements.txt`; the project has no third-party Python dependencies and requires no package-installation step.

## [1.2.0] - Standard-library progress and parallel file streams

### Added

- Replaced the Rich progress interface with a lightweight terminal renderer implemented using only the Python standard library and ANSI terminal control sequences.
- Added per-file progress rows with percentage, transferred size, speed, and ETA when the remote size is known.
- Added a global progress bar covering the complete queue across all selected repositories.
- Added configurable parallel HTTP Range downloads within a single file; the default is 2 streams per file.
- Added automatic fallback to a single streaming request when the server does not support HTTP Range.
- Preserved incomplete parallel range parts for resuming on a later run.
- Added a final report listing files and repositories that were not downloaded or could not be prepared.
- Added a post-session choice to return to the start menu or exit.
- Consolidated source, filename filters, Boolean download switches, concurrency, retry, and error-mode defaults near the top of the script.

### Changed

- Removed the Rich dependency; no third-party Python packages are required.
- Removed interactive questions for optional download categories and error-handling mode. These are configured in the source file.
- The startup download flow asks for simultaneous file downloads and streams per file, then begins automatically after the filter choice.
- Removed the confirmation prompt before starting downloads.
- Excluded filenames are filtered silently instead of being listed individually in the console.
- Error mode is shown as an informational message and can be changed through `DEFAULT_ERROR_MODE` in the source.
- Updated README installation, configuration, parallelism, and progress information.

## [1.1.0] - Rich progress display

- Added Rich-based per-file progress bars and overall queue progress.
- Added transfer speed, ETA, resumed-byte display, and indeterminate progress for unknown file sizes.
- Added the Rich dependency and updated the README.

## [1.0.0] - Initial Python release

- Added an independent Python implementation of GitHub Release Downloader.
- Added repository selection and direct release-tag URL support.
- Added Stable and Pre-release lookup through the GitHub REST API.
- Added filename filtering and optional download categories.
- Added concurrent streamed downloads using the Python standard library.
- Added HTTP Range resume support using `.part` files.
- Added GitHub token detection through environment variables and GitHub CLI.
- Added configurable error handling, retries, console notifications, and persistent logs.
- Added SHA-256 verification when GitHub provides an asset digest.
