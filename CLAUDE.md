# Claude Code & OpenCode Instructions for DiffAnyDoc

Please read **[`AGENTS.md`](AGENTS.md)**, **[`TODO.md`](TODO.md)**, and **[`docs/DESIGN.md`](docs/DESIGN.md)** first.

### Key Rules to Follow Always:
1. **Active Task Board**: Pick up tasks directly from **[`TODO.md`](TODO.md)**. Mark task `[⏳ IN PROGRESS: <Name>]` and `[x] DONE` upon completion.
2. **GNOME & Cinnamon Design System**: **DO NOT DEVIATE from GNOME (libadwaita / HIG) and Cinnamon desktop conventions.** Flat surfaces, clean header bars, `--window-bg-color`, `--view-bg-color`, and no non-native styling.
3. **Commercial Permissive Licensing Only**: Every dependency must be MIT, Apache-2.0, or BSD. **Never add GPL, AGPL, or LGPL**.
4. **Git Branching**: Always work on the `development` branch. Never commit directly to `main`.

## Quick Commands
- **Run all tests**: `.venv/bin/pytest -v`
- **Run web UI**: `.venv/bin/diffanydoc serve --port 8765`
- **Run native desktop app**: `.venv/bin/diffanydoc desktop`
- **Active branch**: Always stay on `development`.
