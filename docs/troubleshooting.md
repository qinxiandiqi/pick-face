# Troubleshooting pick-face

A practical guide for the failure modes that don't fit neatly into the
per-command `--help`. Reference docs: [docs/05 §4](05-data-and-storage.md)
(file-system layout), [docs/11 §3](11-commercial-compliance.md)
(license enforcement), [docs/AGENTS.md](AGENTS.md) (doc index).

If you hit something not covered here, open an issue with the output of
`pick-face --version`, your OS, and the relevant section of `report.md`.

---

## 1. Link fallback warnings on Windows

`pick-face link` tries to use **symbolic links** by default because they
let the same source image live under multiple cluster folders without
duplicating bytes. The fallback chain (per [docs/05 §4.1](05-data-and-storage.md))
is:

| Platform | Files                  | Directories             |
|----------|------------------------|-------------------------|
| Linux    | symlink → copy         | symlink → copy          |
| macOS    | symlink → copy         | symlink → copy          |
| Windows (admin / dev mode) | symlink → hardlink → copy | symlink → junction → copy |
| Windows (unelevated) | hardlink → copy        | junction → copy         |

### 1.1 You see "X/N links fell back to copy instead of 'symlink'"

**Cause.** Windows users running pick-face *without* Administrator
rights *and* without Developer Mode enabled can't create symbolic
links — `os.symlink` returns `OSError: symbolic link privilege not held`.

**Fix.** Pick **one** of the following:

- Enable Developer Mode: Settings → Privacy & security → For developers
  → Developer Mode → On. No reboot needed. Pick-face keeps the
  symlink-first preference.
- Run `pick-face link --no-atomic` from an *elevated* PowerShell. (Less
  recommended; elevation is fragile in scripts.)
- Accept hardlinks: in `pick-face.toml`, set
  ```toml
  [link]
  prefer = "hardlink"
  ```
  This is roughly the same disk usage as symlinks (no per-cluster byte
  duplication), and works on every Windows SKU without privilege.
- Accept copies: `prefer = "copy"`. Disk usage goes up proportionally to
  the number of clusters a photo belongs to — usually 1, occasionally 2
  for borderline photos. Only use this if the source volume is slow /
  read-only.

### 1.2 Hardlink fails with "The system cannot move the file" / Errno 18 (cross-device)

**Cause.** Pick-face's source tree and output tree live on different
volumes (different drives, or one is a network mount). Hardlinks must
live on the same filesystem.

**Fix.** Either keep source and output on the same volume, or set
`prefer = "copy"` in `[link]`.

### 1.3 Output is huge / disk space complaint

The output directory shouldn't be much larger than the source tree as
long as `prefer ∈ {symlink, hardlink, junction}`. If it is, check
`report.md` → **Stats** → **Link kinds**. A large `copy=` count with
`symlink=0` means the OS rejected symlinks — see 1.1 above.

---

## 2. HEIC photos are silently skipped

**Symptom.** `report.md` shows `errors > 0` and the warning is
`ImageDecodeError: install pick-face[heic]`.

**Cause.** macOS / iPhone photos in HEIC format need the
`pillow-heif` runtime; the base install doesn't include it to keep the
wheel small.

**Fix.**

```bash
uv pip install 'pick-face[heic]'
```

Then re-run `pick-face index`. Already-decoded JPEGs are not affected;
the next `pick-face run` will pick up the missing HEIC files.

---

## 3. RAW photos are silently skipped

**Symptom.** `report.md` shows `errors > 0` and the warning is
`ImageDecodeError: install pick-face[raw]`.

**Cause.** Camera RAW files (CR2, NEF, ARW, DNG, RAF, ORF, RW2) need
`rawpy` plus `numpy`. Pick-face first tries the EXIF-embedded JPEG
preview (always present, no extra deps); if the file has no preview
(e.g. smartphone RAW), it falls back to rawpy.

**Fix.**

```bash
uv pip install 'pick-face[raw]'
```

Then re-run `pick-face index`. (The EXIF-thumb fast path is always on
and doesn't need rawpy; rawpy is only for full-resolution decoding.)

---

## 4. "Refusing to start: commercial license check failed"

**Symptom.** Exit code 2 with the message
`Commercial license check failed: accept_noncommercial_model_license=false`
(see [docs/11 §3.6](11-commercial-compliance.md)).

**Cause.** You're using the default `buffalo_l` model, which is
licensed for non-commercial research only, and you haven't set the
explicit opt-in. Pick-face refuses to start to keep you legally safe
(see AC-9 in [docs/11](11-commercial-compliance.md)).

**Fix.** Pick **one** of:

1. **Qualifying research**: set
   ```toml
   [runtime]
   accept_noncommercial_model_license = true
   ```
   in `pick-face.toml`. Be honest about your use case — this is a
   legal declaration, not a software switch.
2. **Self-train** with `face.evoLVe` + `WebFace4M` (MIT-licensed) and
   point pick-face at the resulting ONNX pack — see
   [docs/10 §4](10-model-stack.md).
3. **License InsightFace buffalo_l commercially** — see
   [docs/11 §1](11-commercial-compliance.md).

---

## 5. "No face detected" on photos you can see faces in

The detector (`SCRFD-10G`) only fires on faces larger than roughly 40px
on the short side, with a default `det_thresh=0.5`. For tiny / blurry /
profile faces:

- Lower the threshold: `[detection] det_thresh = 0.3`.
- Resize the photo first (`imagemagick convert in.jpg -resize 2000x2000
  out.jpg`) and re-index the resize.

Don't lower `det_thresh` below 0.2 — false positives explode.

---

## 6. Long-running `pick-face run` interrupted

If you `Ctrl-C` or the OS kills the process, the partially-written
output stays under `<out>.prev-<run_id>/` (atomic-swap means the live
`<out>/` is *always* the previous complete state). Recovery:

```bash
pick-face rollback --to <run_id>           # restore a known-good snapshot
pick-face prune --keep 3                   # tidy old .prev- siblings
```

Exit code 5 (`Interrupted`) means the user (or a SIGTERM) killed us.
Exit code 130 is the standard Python `KeyboardInterrupt`.

---

## 7. SQLite is locked

**Symptom.** `sqlite3.OperationalError: database is locked`.

**Cause.** WAL is enabled but two writers are racing. WAL only allows
one writer at a time; readers don't block writers and vice-versa.

**Fix.** Don't open two `pick-face run` invocations against the same
`--out`. If you've scripted two, serialize them. If you think you
*aren't* running two, check for stale `index.sqlite-shm` / `-wal` files
— they survive a hard kill. Pick-face should clean them up on the next
open, but a manual `rm .cache/index.sqlite-shm` while no process is
running is safe.

---

## 8. Stuck after a crash

```bash
pick-face rebuild --out ./out          # wipe .cache/ + .prev-*
pick-face run --src <dir> --out ./out  # start over from scratch
```

`rebuild --dry-run` lists what would be deleted before you commit.