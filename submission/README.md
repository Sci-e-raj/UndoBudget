# Submission checklist

Upload **two separate files**:

1. `UndoBudget_Code.zip` — source, tests, documentation, and build files. It
   excludes `.git`, compiled files, generated `fs.img`, and the reference PDF.
2. `UndoBudget_Report.pdf` — two A4 pages with a diagram.

Before upload, the team should read the report, add names and roll numbers,
check every statement against its own understanding, and replace any wording
that does not reflect its work. Edit `UndoBudget_Report.md`, then regenerate:

```sh
python3 submission/render_report.py
```

If code changes, regenerate the ZIP so it includes the current working files:

```sh
python3 submission/package_code.py
```

The ZIP was tested by extraction, `make -j2 kernel/kernel fs.img`, and a QEMU
`hello` boot. Do not include a personal `fs.img` in the submission.
