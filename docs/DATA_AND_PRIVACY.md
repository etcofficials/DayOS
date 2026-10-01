# Your data, backups and privacy

## Where data lives

| Running | Data folder |
|---|---|
| `DayOS.exe` | `DayOS Data\` next to the EXE (portable). If that folder can't be written to — for example inside *Program Files* — DayOS asks once and remembers your choice: `%LOCALAPPDATA%\ETC Labs\DayOS` or any folder you pick. |
| From source | The project folder |
| Any | The `DAYOS_HOME` environment variable overrides both |

```
DayOS Data\
├── data\dayos.db      everything you create (one SQLite database)
├── backups\           backups (yours, automatic and safety copies)
├── exports\           JSON / CSV / Markdown exports
├── logs\dayos.log     technical log — no note, task, clipboard, money or AI contents
└── .cache\            rebuildable files (icons, opened attachment copies)
```

The single-file EXE unpacks its program files to a private temporary folder while it
runs. Your data is never stored there.

## Backups and recovery

* **Back up now** (Settings → Data & backups) writes a verified snapshot.
* **Automatic backup:** once a week by default (daily or off are also available). It runs in the background shortly after start-up. Only automatic backups are rotated, and you choose how many to keep (default 10).
* **Safety backups** are written automatically before every database upgrade, JSON import and restore. They, and your manual backups, are never deleted by DayOS.
* **Restore…** checks the file (integrity, schema version, contents), shows what it holds, and asks before replacing anything. It saves your current data first.
* **Export:** JSON (everything, re-importable; clipboard history only if you choose), CSV (spreadsheets), Markdown (SecondBrain), and CSV for money entries.

**If something goes wrong:**
1. Close DayOS and copy the whole `DayOS Data` folder somewhere safe.
2. Start DayOS and use Settings → Data & backups → Restore… with the newest good backup.
3. If DayOS won't start, rename `data\dayos.db`, copy a file from `backups\` to `data\dayos.db`, and start DayOS. It upgrades older backups automatically, after backing them up.
4. Run *Check database health*.

## Privacy controls

* **No telemetry, no account.** Nothing is sent anywhere unless you turn on an online feature.
* **Online features**: weather, news, GitHub and AI are all off by default. Each one names the service it uses.
  * **Weather:** sends only the coordinates of the place you choose to Open-Meteo.com. Data is CC BY 4.0, free for non-commercial use, no key.
  * **News:** downloads the publishers' public RSS/Atom feeds for the topics you choose. Only their headlines and short descriptions are shown, with links to the original articles.
  * **GitHub:** read-only REST requests for repositories linked to your projects. A token is optional.
  * **AI:** your own API key. DayOS shows the exact text before each request and sends nothing until you confirm. AI-made StudyForge questions are saved as *AI* and *not verified*. Clipboard history is never sent.
* **Secrets:** API keys and tokens are kept in Windows Credential Manager (as `DayOS/…`) for your Windows account. They are never stored in the database, settings, backups, exports, logs or the program. Remove them in Settings → GitHub or Settings → AI, or in Windows' Credential Manager.
* **ClipVault:**
  * It's off until you turn it on, after it explains what is stored. While it's off or paused, the clipboard isn't read at all.
  * It skips copies that apps mark as private (most password managers), copies from known password managers, text that looks like passwords, keys, one-time codes or card numbers, and anything matching your exclusion rules. This detection isn't perfect, so pause it before copying something sensitive.
  * It keeps history for the period you choose, and you can clear it at any time.
* **FilePilot:** scans are read-only. It changes files only after you preview and confirm, never deletes permanently (it uses the Recycle Bin), and never overwrites anything.
* **AudioDock:** the microphone is opened only while you run the meter or a test recording. Recordings stay in memory.
