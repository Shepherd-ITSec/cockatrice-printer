# Cockatrice Printer

Generate printable **A4 card sheets** from already-downloaded **Cockatrice XML card databases**.

This project is distributed as a ready-to-run Python application using **uv**.

---

# Installation

## Via UV

```bash
uv tool install git+https://github.com/yourusername/cockatrice-printer.git@main
```

---

# Running Cockatrice Printer

Because the project defines a command-line entry point, run it through uv:

```bash
uv run cockatrice-printer --help
```

For example:

```bash
uv run cockatrice-printer list --xml-dir xml
```

or:

```bash
uv run cockatrice-printer print --xml-dir xml --set SOH
```

`uv run` automatically uses the project's environment.

You can also use:

```bash
uv run cockatrice-printer validate --xml-dir xml --set SOH
```

---

# Input XML files

Place your already-downloaded Cockatrice XML files in an `xml/` directory:

```text
cockatrice-printer/
├── cockatrice_printer.py
├── pyproject.toml
├── uv.lock
├── README.md
└── xml/
    ├── cards.xml
    └── another-set.xml
```

The program expects Cockatrice card database XML.

It also handles XML copied from a browser that contains text before the actual XML document, such as:

```text
This XML file does not appear to have any style information...
```

The parser searches for the `<cockatrice_carddatabase>` document and parses the XML from there.

---

# Find available sets

Before printing, list the XML files and sets discovered by the program:

```bash
uv run cockatrice-printer list --xml-dir xml
```

`sets` is also available as an alias:

```bash
uv run cockatrice-printer sets --xml-dir xml
```

The output shows the set codes that can be passed to `--set`.

For example:

```text
SOH
HCJ
```

You can then print one of those sets:

```bash
uv run cockatrice-printer print --xml-dir xml --set SOH
```

---

# Validate your XML

Validate all XML files:

```bash
uv run cockatrice-printer validate --xml-dir xml
```

Validate a specific set:

```bash
uv run cockatrice-printer validate \
    --xml-dir xml \
    --set SOH
```

This is useful before starting a large print job.

---

# Print a set

Print an entire set:

```bash
uv run cockatrice-printer print \
    --xml-dir xml \
    --set SOH
```

The PDF is written to the output directory.

By default, the program uses:

- A4 paper
- 9 cards per page
- 3 × 3 layout
- 63 × 88 mm cards
- 2 mm gaps between cards
- centered layout
- cutting corner guides

---

# Cutting guides

Use full cut lines:

```bash
uv run cockatrice-printer print \
    --xml-dir xml \
    --set SOH \
    --cut-lines
```

Disable cutting guides:

```bash
uv run cockatrice-printer print \
    --xml-dir xml \
    --set SOH \
    --cut-style none
```

Available styles are:

```text
none
corners
lines
```

---

# Filter cards

Create a text file containing the exact card names you want:

```text
wanted.txt
```

Example:

```text
Card Name One
Card Name Two
Card Name Three
```

Then:

```bash
uv run cockatrice-printer print \
    --xml-dir xml \
    --set SOH \
    --names-file wanted.txt
```

Only cards whose names exactly match the entries in the file are printed.

---

# Exclude tokens

To exclude Cockatrice token cards:

```bash
uv run cockatrice-printer print \
    --xml-dir xml \
    --set SOH \
    --exclude-tokens
```

---

# Duplex printing

Generate reverse-side pages for duplex printing:

```bash
uv run cockatrice-printer print \
    --xml-dir xml \
    --set SOH \
    --duplex
```

You can choose how the reverse side is transformed:

```bash
uv run cockatrice-printer print \
    --xml-dir xml \
    --set SOH \
    --duplex \
    --back rotate180
```

Available modes:

```text
normal
mirror
rotate180
```

### Test duplex alignment first

Printer duplex behavior varies.

Before printing an entire set, print one test sheet and verify that the front and back align correctly.

If the reverse side is incorrectly oriented, try:

```bash
--back rotate180
```

or:

```bash
--back mirror
```

Also make sure your printer is set to **Actual Size / 100%** and is not scaling the PDF.

---

# Custom card back

Supply your own card-back image:

```bash
uv run cockatrice-printer print \
    --xml-dir xml \
    --set SOH \
    --duplex \
    --card-back card-back.png
```

If `--duplex` is enabled without a custom card back, the program generates a default card back.

---

# Registration marks

Add printer registration marks:

```bash
uv run cockatrice-printer print \
    --xml-dir xml \
    --set SOH \
    --registration
```

These can help when checking printer alignment.

---

# Card spacing and margins

The default gap is 2 mm.

For a 1 mm gap:

```bash
uv run cockatrice-printer print \
    --xml-dir xml \
    --set SOH \
    --gap 1
```

For a 3 mm gap:

```bash
uv run cockatrice-printer print \
    --xml-dir xml \
    --set SOH \
    --gap 3
```

The default outer margin is 5 mm.

For a 4 mm margin:

```bash
uv run cockatrice-printer print \
    --xml-dir xml \
    --set SOH \
    --margin 4
```

The default card size is 63 × 88 mm.

---

# Image caching

Card images are downloaded from the `picURL` values in the Cockatrice XML.

Downloaded images are stored in the local image cache:

```text
images/
```

When the same cards are printed again, cached images are reused rather than downloaded again.

The downloader also supports retries and configurable timeouts:

```bash
uv run cockatrice-printer print \
    --xml-dir xml \
    --set SOH \
    --retries 5 \
    --timeout 60
```

---

# Output

A typical project directory after running the program looks like:

```text
cockatrice-printer/
├── cockatrice_printer.py
├── pyproject.toml
├── uv.lock
├── README.md
├── xml/
│   └── *.xml
├── images/
│   └── cached card images
└── output/
    ├── *.pdf
    └── *.csv
```

The PDF contains the printable sheets.

The CSV manifest contains information about the cards included in the print run, including their sheet/slot information and cached image paths.

---

# Recommended first run

After downloading the project:

```bash
cd cockatrice-printer
```

Install/synchronize the already-declared dependencies:

```bash
uv sync
```

Check that the application starts:

```bash
uv run cockatrice-printer --help
```

Put your XML files in:

```text
xml/
```

List the available sets:

```bash
uv run cockatrice-printer list --xml-dir xml
```

Validate the set you want:

```bash
uv run cockatrice-printer validate \
    --xml-dir xml \
    --set SOH
```

Then generate the PDF:

```bash
uv run cockatrice-printer print \
    --xml-dir xml \
    --set SOH
```

---

# Updating the environment

If the project already contains a `uv.lock` file, use:

```bash
uv sync
```

This recreates/synchronizes the environment from the project configuration and lock file.

To deliberately update dependency versions:

```bash
uv lock --upgrade
uv sync
```

For normal use, **do not** use `--upgrade`; `uv sync` is enough.

---

# Git / project files

The important files are:

```text
pyproject.toml
uv.lock
cockatrice_printer.py
README.md
```

Commit `pyproject.toml` and `uv.lock` to version control.

Generated files such as cached images, PDFs, and the local virtual environment generally should not be committed.

A suitable `.gitignore` is included:

```gitignore
.venv/
__pycache__/
*.py[cod]

images/
output/
xml/
```

---

# Command summary

List sets:

```bash
uv run cockatrice-printer list --xml-dir xml
```

Validate:

```bash
uv run cockatrice-printer validate --xml-dir xml --set SOH
```

Print:

```bash
uv run cockatrice-printer print --xml-dir xml --set SOH
```

Print with full cut lines:

```bash
uv run cockatrice-printer print --xml-dir xml --set SOH --cut-lines
```

Print duplex:

```bash
uv run cockatrice-printer print --xml-dir xml --set SOH --duplex
```

Filter by names:

```bash
uv run cockatrice-printer print \
    --xml-dir xml \
    --set SOH \
    --names-file wanted.txt
```

Exclude tokens:

```bash
uv run cockatrice-printer print \
    --xml-dir xml \
    --set SOH \
    --exclude-tokens
```

Show help:

```bash
uv run cockatrice-printer --help
```

---

# Troubleshooting

## `uv: command not found`

This means uv itself is not installed or is not available on your `PATH`.

Install uv using its official installation instructions, then return to this project and run:

```bash
uv sync
```

This is the **only installation step outside the project**.

## Dependencies are missing

From the project directory:

```bash
uv sync
```

Do not install the Python packages globally.

## No sets are found

Check that your XML files are actually inside the directory passed to:

```bash
--xml-dir
```

For example:

```bash
uv run cockatrice-printer list --xml-dir xml
```

## Image downloads fail

Try increasing the retry count:

```bash
uv run cockatrice-printer print \
    --xml-dir xml \
    --set SOH \
    --retries 5
```

Or increase the timeout:

```bash
uv run cockatrice-printer print \
    --xml-dir xml \
    --set SOH \
    --timeout 60
```

## Printed cards are the wrong physical size

The generated cards are intended to be **63 × 88 mm**.

When printing the PDF, select:

```text
Actual Size
100%
```

and disable options such as:

```text
Fit
Fit to Page
Scale to Fit
Shrink oversized pages
```

The printer driver must not apply additional scaling.

## Duplex pages are misaligned

Print a single test sheet first.

Try:

```bash
--back rotate180
```

or:

```bash
--back mirror
```

Printer paper-feed and duplex mechanisms differ, so a test page is strongly recommended.

---

# License / source data

This application is a local utility for converting Cockatrice card database XML into printable sheets.

The generated PDFs contain card artwork and card data referenced by the input XML. Make sure your use and redistribution of generated files complies with the rights and licenses applicable to the Hellscube project, its card artwork, and any other included content.
