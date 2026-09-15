#!/usr/bin/env python3
"""
Cockatrice printable-sheet generator.

Input:
    One or more Cockatrice XML files downloaded from Hellfall.

Main features:
    * list all XML files and sets found in a directory
    * print a complete set or a filtered list
    * 3 x 3 Magic-card layout on A4
    * 63 x 88 mm cards with configurable gaps/margins
    * crop/cutting marks or full cut lines
    * optional registration marks
    * cached image downloads
    * retries and image validation
    * duplicate-name-safe filenames
    * CSV manifest
    * optional duplex back sheets
    * optional card backs
    * dry-run / validation mode
    * accepts normal XML and browser-copied XML beginning with
      "This XML file does not appear..." (as in the supplied example)

Install:
    python -m pip install requests pillow reportlab

Examples:
    python cockatrice-printer.py list --xml-dir xml
    python cockatrice-printer.py sets --xml-dir xml
    python cockatrice-printer.py print --xml-dir xml --set SOH
    python cockatrice-printer.py print --xml-dir xml --set SOH --cut-lines
    python cockatrice-printer.py print --xml-dir xml --set SOH --duplex
    python cockatrice-printer.py print --xml-dir xml --set SOH --duplex --back rotate180
    python cockatrice-printer.py print --xml-dir xml --set SOH --names-file wanted.txt
    python cockatrice-printer.py validate --xml-dir xml --set SOH
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import re
import sys
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path
from tqdm import tqdm

import requests
from PIL import Image, ImageOps
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas


# ----------------------------- print geometry -----------------------------

MM = 72.0 / 25.4

A4_W, A4_H = A4

CARD_W_MM = 63.0
CARD_H_MM = 88.0

COLS = 3
ROWS = 3

DEFAULT_GAP_MM = 0.0
DEFAULT_MARGIN_MM = 0.0

CARD_W = CARD_W_MM * MM
CARD_H = CARD_H_MM * MM


@dataclass
class Card:
    name: str
    text: str
    set_code: str
    rarity: str
    number: str
    uuid: str
    muid: str
    image_url: str
    layout: str = ""
    side: str = ""
    card_type: str = ""
    mana_cost: str = ""
    cmc: str = ""
    power_toughness: str = ""


@dataclass
class SetInfo:
    code: str
    longname: str
    settype: str


# ----------------------------- general helpers ----------------------------


def mm(value: float) -> float:
    return value * MM


def natural_number(value: str):
    """Sort numeric card numbers numerically and other values afterward."""
    value = (value or "").strip()
    try:
        return (0, int(value), "")
    except ValueError:
        return (1, 0, value.lower())


def safe_filename(value: str, max_len: int = 160) -> str:
    value = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", value.strip())
    value = re.sub(r"\s+", " ", value).strip(" .")
    return (value or "unnamed")[:max_len]


def slug(value: str) -> str:
    value = re.sub(r"[^A-Za-z0-9._-]+", "_", value.strip())
    return value.strip("._-") or "output"


def strip_namespace(root: ET.Element) -> ET.Element:
    """Remove XML namespaces if a future Cockatrice export adds one."""
    for element in root.iter():
        if "}" in element.tag:
            element.tag = element.tag.split("}", 1)[1]
    return root


def xml_bytes_from_file(path: Path) -> bytes:
    data = path.read_bytes()

    # The supplied browser-copied example starts with this explanatory line.
    marker = b"<cockatrice_carddatabase"
    pos = data.find(marker)
    if pos > 0:
        data = data[pos:]

    return data


# ----------------------------- XML handling -------------------------------


def parse_cockatrice_xml(path: Path):
    try:
        root = ET.fromstring(xml_bytes_from_file(path))
    except ET.ParseError as exc:
        raise ValueError(f"{path}: invalid Cockatrice XML: {exc}") from exc

    root = strip_namespace(root)

    sets: dict[str, SetInfo] = {}
    for elem in root.findall("./sets/set"):
        code = (elem.findtext("name") or "").strip()
        if not code:
            continue
        sets[code.upper()] = SetInfo(
            code=code,
            longname=(elem.findtext("longname") or "").strip(),
            settype=(elem.findtext("settype") or "").strip(),
        )

    cards: list[Card] = []

    for card_elem in root.findall("./cards/card"):
        name = (card_elem.findtext("name") or "").strip()
        if not name:
            continue

        prop = card_elem.find("prop")
        prop = prop if prop is not None else ET.Element("prop")

        pt = (prop.findtext("pt") or "").strip()

        for set_elem in card_elem.findall("set"):
            code = (set_elem.text or "").strip()
            if not code:
                continue

            cards.append(Card(
                name=name,
                text=(card_elem.findtext("text") or "").strip(),
                set_code=code.upper(),
                rarity=set_elem.attrib.get("rarity", ""),
                number=set_elem.attrib.get("num", ""),
                uuid=set_elem.attrib.get("uuid", ""),
                muid=set_elem.attrib.get("muid", ""),
                image_url=set_elem.attrib.get("picURL", ""),
                layout=(prop.findtext("layout") or "").strip(),
                side=(prop.findtext("side") or "").strip(),
                card_type=(prop.findtext("type") or "").strip(),
                mana_cost=(prop.findtext("manacost") or "").strip(),
                cmc=(prop.findtext("cmc") or "").strip(),
                power_toughness=pt,
            ))

    return sets, cards


def discover_xml(xml_dir: Path) -> list[Path]:
    files = sorted(
        [*xml_dir.glob("*.xml"), *xml_dir.glob("*.XML")],
        key=lambda p: p.name.lower(),
    )
    # Some users save downloaded XML as .txt.
    files += sorted(
        [*xml_dir.glob("*.txt"), *xml_dir.glob("*.TXT")],
        key=lambda p: p.name.lower(),
    )

    unique = []
    seen = set()
    for p in files:
        if p.resolve() not in seen:
            unique.append(p)
            seen.add(p.resolve())
    return unique


def load_all_xml(xml_dir: Path):
    result = []
    errors = []

    for path in discover_xml(xml_dir):
        try:
            sets, cards = parse_cockatrice_xml(path)
            result.append((path, sets, cards))
        except Exception as exc:
            errors.append((path, str(exc)))

    return result, errors


def find_set(xml_dir: Path, set_code: str):
    set_code = set_code.upper()

    matches = []
    for path, sets, cards in load_all_xml(xml_dir)[0]:
        if set_code in sets:
            matches.append((path, sets[set_code], cards))

    if not matches:
        raise SystemExit(
            f"Set '{set_code}' was not found in {xml_dir}. "
            f"Run 'sets' to see available sets."
        )

    # Normally there is exactly one. If several XMLs contain it, prefer the
    # one containing the largest number of cards and tell the user.
    matches.sort(
        key=lambda x: sum(c.set_code == set_code for c in x[2]),
        reverse=True,
    )

    if len(matches) > 1:
        tqdm.write("Warning: set occurs in multiple XML files; using the one "
              "with the most cards:", file=sys.stderr)
        for path, info, all_cards in matches:
            count = sum(c.set_code == set_code for c in all_cards)
            tqdm.write(f"  {path.name}: {count} cards", file=sys.stderr)

    path, info, all_cards = matches[0]
    selected = [c for c in all_cards if c.set_code == set_code]
    selected.sort(key=lambda c: natural_number(c.number))
    return path, info, selected


# ----------------------------- card filtering -----------------------------


def read_names_file(path: Path) -> set[str]:
    names = set()
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            names.add(line.casefold())
    return names


def filter_cards(
    cards: list[Card],
    names_file: Path | None = None,
    exclude_tokens: bool = False,
) -> list[Card]:
    result = cards

    if names_file:
        wanted = read_names_file(names_file)
        result = [c for c in result if c.name.casefold() in wanted]

    if exclude_tokens:
        # Cockatrice token cards are normally in HCT/SFT, but this also
        # catches token layouts if a custom XML places them elsewhere.
        result = [
            c for c in result
            if c.layout.lower() != "token"
        ]

    return result


# ----------------------------- image cache --------------------------------


class ImageCache:
    def __init__(self, directory: Path, timeout: int = 30, retries: int = 3):
        self.directory = directory
        self.directory.mkdir(parents=True, exist_ok=True)
        self.timeout = timeout
        self.retries = retries

        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": (
                "CockatricePrintable/1.0 "
                "(Python requests; card-sheet generator)"
            )
        })

    def filename(self, card: Card) -> Path:
        # UUID is ideal because it is stable and avoids collisions.
        identity = card.uuid or card.muid or (
            f"{card.set_code}-{card.number}-{card.name}"
        )
        digest = hashlib.sha1(identity.encode("utf-8")).hexdigest()[:12]
        return self.directory / (
            f"{safe_filename(card.number or 'no-num')}_"
            f"{safe_filename(card.name)}_{digest}.png"
        )

    def get(self, card: Card) -> Path:
        target = self.filename(card)

        if target.exists() and target.stat().st_size > 1000:
            self.validate(target)
            return target

        if not card.image_url:
            raise RuntimeError(
                f"No picURL for '{card.name}' ({card.set_code} #{card.number})"
            )

        last_error = None

        for attempt in range(1, self.retries + 1):
            try:
                response = self.session.get(
                    card.image_url,
                    timeout=self.timeout,
                )
                response.raise_for_status()

                image = Image.open(io.BytesIO(response.content))
                image = ImageOps.exif_transpose(image).convert("RGB")
                image.save(target, "PNG", optimize=True)

                self.validate(target)
                return target

            except Exception as exc:
                last_error = exc
                if attempt < self.retries:
                    time.sleep(1.5 * attempt)

        raise RuntimeError(
            f"Could not download '{card.name}' after "
            f"{self.retries} attempts: {last_error}"
        )

    @staticmethod
    def validate(path: Path):
        with Image.open(path) as image:
            image.verify()


# ----------------------------- PDF drawing --------------------------------


def fit_crop_image(path: Path, out_path: Path, target_ratio: float):
    """
    Crop the image to the exact Magic-card aspect ratio.

    Images should already be card-shaped. Cropping rather than
    stretching protects the card proportions if an image has tiny borders.
    """
    with Image.open(path) as original:
        image = ImageOps.exif_transpose(original).convert("RGB")
        w, h = image.size
        ratio = w / h

        if abs(ratio - target_ratio) > 0.002:
            if ratio > target_ratio:
                new_w = int(h * target_ratio)
                left = (w - new_w) // 2
                image = image.crop((left, 0, left + new_w, h))
            else:
                new_h = int(w / target_ratio)
                top = (h - new_h) // 2
                image = image.crop((0, top, w, top + new_h))

        image.save(out_path, "JPEG", quality=96)


def draw_crop_marks(
    c: canvas.Canvas,
    x: float,
    y: float,
    w: float,
    h: float,
    length: float = mm(3),
    offset: float = mm(0.8),
    line_width: float = 0.35,
):
    """
    Corner crop marks around a card.

    These deliberately sit outside the card image so they don't obscure
    printed card content.
    """
    c.saveState()
    c.setLineWidth(line_width)

    # bottom-left
    c.line(x - offset - length, y, x - offset, y)
    c.line(x, y - offset - length, x, y - offset)

    # bottom-right
    c.line(x + w + offset, y, x + w + offset + length, y)
    c.line(x + w, y - offset - length, x + w, y - offset)

    # top-left
    c.line(x - offset - length, y + h, x - offset, y + h)
    c.line(x, y + h + offset, x, y + h + offset + length)

    # top-right
    c.line(x + w + offset, y + h, x + w + offset + length, y + h)
    c.line(x + w, y + h + offset, x + w, y + h + offset + length)

    c.restoreState()

def draw_page_cut_lines(
    c: canvas.Canvas,
    positions: list[tuple[float, float]],
    line_width: float = 0.25,
):
    """Draw continuous cut lines across the entire A4 page."""
    c.saveState()
    c.setLineWidth(line_width)

    # Get every X boundary from the actual card positions.
    x_lines = sorted(set(
        [x for x, _ in positions] +
        [x + CARD_W for x, _ in positions]
    ))

    # Get every Y boundary from the actual card positions.
    y_lines = sorted(set(
        [y for _, y in positions] +
        [y + CARD_H for _, y in positions]
    ))

    # Vertical cuts: extend from the bottom to the top of A4.
    for x in x_lines:
        c.line(x, 0, x, A4_H)

    # Horizontal cuts: extend from the left to the right of A4.
    for y in y_lines:
        c.line(0, y, A4_W, y)

    c.restoreState()


def draw_registration_marks(c: canvas.Canvas):
    """
    Small registration targets near the A4 corners.

    They are useful when experimenting with a printer's duplex alignment.
    """
    c.saveState()
    c.setLineWidth(0.25)
    r = mm(1.5)
    margin = mm(3)

    for x, y in [
        (margin, margin),
        (A4_W - margin, margin),
        (margin, A4_H - margin),
        (A4_W - margin, A4_H - margin),
    ]:
        c.circle(x, y, r, stroke=1, fill=0)
        c.line(x - r * 1.6, y, x + r * 1.6, y)
        c.line(x, y - r * 1.6, x, y + r * 1.6)

    c.restoreState()

def draw_card_image(
    c: canvas.Canvas,
    image_path: Path,
    x: float,
    y: float,
    card: Card,
):
    """
    Draw a card image into the normal 63 x 88 mm card slot.

    Fuse/split-style cards are rotated 90 degrees so the two halves
    are oriented correctly when printed on a normal card.
    """
    rotate_image = card.layout.lower() in {
        "split",
        "aftermath",
        "flip",
        "fuse",
    }

    if rotate_image:
        c.saveState()

        # Rotate the image 90 degrees around the center of the card.
        c.translate(x + CARD_W / 2, y + CARD_H / 2)
        c.rotate(90)

        # After rotation, swap width/height.
        c.drawImage(
            str(image_path),
            -CARD_H / 2,
            -CARD_W / 2,
            width=CARD_H,
            height=CARD_W,
            preserveAspectRatio=False,
            mask="auto",
        )

        c.restoreState()
    else:
        c.drawImage(
            str(image_path),
            x,
            y,
            width=CARD_W,
            height=CARD_H,
            preserveAspectRatio=False,
            mask="auto",
        )



def page_positions(gap_mm: float, margin_mm: float):
    gap = mm(gap_mm)
    margin = mm(margin_mm)

    grid_w = COLS * CARD_W + (COLS - 1) * gap
    grid_h = ROWS * CARD_H + (ROWS - 1) * gap

    if grid_w + 2 * margin > A4_W + 0.01:
        raise ValueError(
            "3 x 63 mm cards plus gaps/margins do not fit A4 width"
        )

    if grid_h + 2 * margin > A4_H + 0.01:
        raise ValueError(
            "3 x 88 mm cards plus gaps/margins do not fit A4 height"
        )

    # Center the card grid in the printable page area defined by margin.
    available_w = A4_W - 2 * margin
    available_h = A4_H - 2 * margin

    start_x = margin + (available_w - grid_w) / 2
    start_y = margin + (available_h - grid_h) / 2

    positions = []

    for row in range(ROWS):
        for col in range(COLS):
            x = start_x + col * (CARD_W + gap)
            y = (
                A4_H
                - start_y
                - CARD_H
                - row * (CARD_H + gap)
            )
            positions.append((x, y))

    return positions


def draw_sheet(
    c: canvas.Canvas,
    cards: list[Card],
    images: list[Path],
    *,
    gap_mm: float,
    margin_mm: float,
    cut_style: str,
    registration: bool,
    mirror: bool = False,
    rotate180: bool = False,
    label: str = "",
):
    positions = page_positions(gap_mm, margin_mm)

    if registration:
        draw_registration_marks(c)

    temp_dir = images[0].parent / ".print_temp"
    temp_dir.mkdir(exist_ok=True)

    for index, (card, image_path) in tqdm(enumerate(zip(cards, images)), desc="Drawing cards", total=len(cards), leave=False, unit="card"):
        x, y = positions[index]

        if mirror or rotate180:
            c.saveState()

            if rotate180:
                c.translate(x + CARD_W, y + CARD_H)
                c.rotate(180)
                draw_path = image_path
                draw_x = 0
                draw_y = 0
            elif mirror:
                c.translate(x + CARD_W, y)
                c.scale(-1, 1)
                draw_path = image_path
                draw_x = 0
                draw_y = 0

            # We draw the original image. A printer-facing back sheet can be
            # mirrored/rotated at the page level without changing the image.
            c.drawImage(
                str(draw_path),
                draw_x,
                draw_y,
                width=CARD_W,
                height=CARD_H,
                preserveAspectRatio=False,
                mask="auto",
            )
            c.restoreState()
        else:
            draw_card_image(
                c,
                image_path,
                x,
                y,
                card,
            )


        if cut_style == "corners":
            draw_crop_marks(c, x, y, CARD_W, CARD_H)
    if cut_style == "lines":
        draw_page_cut_lines(
            c,
            positions,
            line_width=0.25,
        )


    if label:
        c.saveState()
        c.setFont("Helvetica", 5)
        c.drawCentredString(A4_W / 2, mm(1.8), label)
        c.restoreState()

    c.showPage()


def build_pdf(
    cards: list[Card],
    image_paths: list[Path],
    output: Path,
    *,
    gap_mm: float,
    margin_mm: float,
    cut_style: str,
    registration: bool,
    duplex: bool,
    duplex_back: str,
    include_card_back: Path | None,
):
    per_page = COLS * ROWS

    c = canvas.Canvas(str(output), pagesize=A4)
    c.setTitle("Cockatrice printable cards")

    # Front sheets.
    for page_start in tqdm(range(0, len(cards), per_page), desc="Drawing pages", total=len(cards) // per_page + 1, unit="page"):
        page_cards = cards[page_start:page_start + per_page]
        page_images = image_paths[page_start:page_start + per_page]

        # Pad neither cards nor positions; partial final sheets are allowed.
        draw_sheet(
            c,
            page_cards,
            page_images,
            gap_mm=gap_mm,
            margin_mm=margin_mm,
            cut_style=cut_style,
            registration=registration,
            label=f"Fronts — page {page_start // per_page + 1}",
        )

    if duplex:
        # Back pages are intentionally generated in the same page order.
        # If the printer's duplex mechanism flips the long edge, use rotate180
        # or mirror depending on how the printer feeds the sheet.
        #
        # With no supplied card-back artwork, the reverse pages use a very
        # light "CARD BACK" label. A real card-back image can be supplied with
        # --card-back.
        back_images: list[Path] = []

        if include_card_back:
            # Make a temporary copy reference repeated as needed.
            back_images = [include_card_back] * len(cards)
        else:
            # Create a printable generated back.
            back_path = output.parent / ".generated_card_back.png"
            make_default_back(back_path)
            back_images = [back_path] * len(cards)

        for page_start in tqdm(range(0, len(cards), per_page), desc="Back sheets", total=len(cards) // per_page + 1, unit="sheet"):
            page_cards = cards[page_start:page_start + per_page]
            page_images = back_images[page_start:page_start + per_page]

            # The image itself remains upright; the sheet transform determines
            # duplex registration.
            mirror = duplex_back == "mirror"
            rotate = duplex_back == "rotate180"

            draw_sheet(
                c,
                page_cards,
                page_images,
                gap_mm=gap_mm,
                margin_mm=margin_mm,
                cut_style=cut_style,
                registration=registration,
                mirror=mirror,
                rotate180=rotate,
                label=(
                    f"Backs — page {page_start // per_page + 1} "
                    f"({duplex_back})"
                ),
            )
    tqdm.write("Saving...")
    c.save()


def make_default_back(path: Path):
    """Generate a simple neutral card-back image with PIL."""
    from PIL import ImageDraw, ImageFont

    width, height = 750, 1050
    image = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(image)

    # Use the default PIL font so this has no OS-font dependency.
    try:
        font = ImageFont.truetype("DejaVuSans.ttf", 42)
    except Exception:
        font = ImageFont.load_default()

    draw.rectangle((15, 15, width - 15, height - 15), outline="black", width=8)
    text = "cockatrice"
    bbox = draw.textbbox((0, 0), text, font=font)
    tw = bbox[2] - bbox[0]
    th = bbox[3] - bbox[1]
    draw.text(
        ((width - tw) / 2, (height - th) / 2),
        text,
        fill="black",
        font=font,
    )
    image.save(path, "PNG")


# ----------------------------- manifest -----------------------------------


def write_manifest(
    cards: list[Card],
    path: Path,
    image_paths: list[Path] | None = None,
):
    with path.open("w", newline="", encoding="utf-8") as f:
        fields = [
            "sheet_index",
            "slot",
            "name",
            "set",
            "number",
            "uuid",
            "muid",
            "rarity",
            "layout",
            "side",
            "type",
            "mana_cost",
            "cmc",
            "power_toughness",
            "image_url",
            "local_image",
        ]
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()

        for i, card in enumerate(cards):
            writer.writerow({
                "sheet_index": i // 9 + 1,
                "slot": i % 9 + 1,
                "name": card.name,
                "set": card.set_code,
                "number": card.number,
                "uuid": card.uuid,
                "muid": card.muid,
                "rarity": card.rarity,
                "layout": card.layout,
                "side": card.side,
                "type": card.card_type,
                "mana_cost": card.mana_cost,
                "cmc": card.cmc,
                "power_toughness": card.power_toughness,
                "image_url": card.image_url,
                "local_image": (
                    str(image_paths[i])
                    if image_paths else ""
                ),
            })


# ----------------------------- CLI commands -------------------------------


def cmd_list(args):
    xml_dir = Path(args.xml_dir)
    files = discover_xml(xml_dir)

    if not files:
        tqdm.write(f"No XML/TXT files found in {xml_dir}")
        return 1

    for path in files:
        try:
            sets, cards = parse_cockatrice_xml(path)
        except Exception as exc:
            tqdm.write(f"\n{path.name}\n  ERROR: {exc}")
            continue

        tqdm.write(f"\n{path.name}")
        tqdm.write(f"  cards: {len(cards)}")

        for code, info in sorted(sets.items()):
            count = sum(c.set_code == code for c in cards)
            tqdm.write(
                f"  {code:8} {count:4} cards  "
                f"{info.longname}"
            )

    return 0


def cmd_sets(args):
    return cmd_list(args)


def cmd_validate(args):
    xml_dir = Path(args.xml_dir)

    if args.set:
        path, info, cards = find_set(xml_dir, args.set)
        tqdm.write(f"XML:  {path}")
        tqdm.write(f"Set:  {info.code} — {info.longname}")
        tqdm.write(f"Cards: {len(cards)}")

        missing = [c for c in cards if not c.image_url]
        if missing:
            tqdm.write(f"Missing picURL: {len(missing)}")
            for c in missing[:20]:
                tqdm.write(f"  #{c.number} {c.name}")
            return 2

        tqdm.write("All selected cards have image URLs.")
        return 0

    # Validate every XML.
    all_data, errors = load_all_xml(xml_dir)
    for path, sets, cards in all_data:
        tqdm.write(f"OK  {path.name}: {len(cards)} card entries")

    for path, error in errors:
        tqdm.write(f"ERR {path.name}: {error}")

    return 2 if errors else 0


def cmd_print(args):
    xml_dir = Path(args.xml_dir)

    path, info, cards = find_set(xml_dir, args.set)

    cards = filter_cards(
        cards,
        names_file=Path(args.names_file) if args.names_file else None,
        exclude_tokens=args.exclude_tokens,
    )

    if not cards:
        raise SystemExit("No cards remain after filtering.")

    tqdm.write(f"Source XML : {path}")
    tqdm.write(f"Set        : {info.code} — {info.longname}")
    tqdm.write(f"Cards      : {len(cards)}")
    tqdm.write(f"Sheets     : {(len(cards) + 8) // 9}")
    tqdm.write(
        f"Card size  : {CARD_W_MM:g} x {CARD_H_MM:g} mm"
    )
    tqdm.write(
        f"Margins    : {args.margin} mm"
    )
    tqdm.write(
        f"Gap        : {args.gap} mm"
    )
    tqdm.write(
        f"Cut style  : {args.cut_style}"
    )


    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    base = args.output or f"{slug(info.code)}"

    if not base.lower().endswith(".pdf"):
        base += ".pdf"

    output = output_dir / base
    manifest = output.with_suffix(".csv")

    cache = ImageCache(
        Path(args.image_dir),
        timeout=args.timeout,
        retries=args.retries,
    )

    image_paths = []

    tqdm.write("\nChecking/downloading images...")
    failures = []

    pbar = tqdm(
        enumerate(cards, 1),
        desc="Downloading images",
        total=len(cards),
        leave=True,
    )

    for i, card in pbar:
        char_len = 25
        cardname = card.name[:char_len].ljust(char_len)
        try:
            pbar.set_postfix_str(
                f"{cardname}",
                refresh=False,
            )
            image_paths.append(cache.get(card))
        except Exception:
            tqdm.write(f"#{card.number} {card.name} FAILED")


    if failures:
        tqdm.write(
            f"\nAborting: {len(failures)} card image(s) failed. "
            "No incomplete PDF was produced.",
            file=sys.stderr,
        )
        return 2

    card_back = Path(args.card_back) if args.card_back else None
    if card_back and not card_back.exists():
        raise SystemExit(f"Card-back image not found: {card_back}")

    tqdm.write("\nWriting PDF...")
    build_pdf(
        cards,
        image_paths,
        output,
        gap_mm=args.gap,
        margin_mm=args.margin,
        cut_style=args.cut_style,
        registration=args.registration,
        duplex=args.duplex,
        duplex_back=args.back,
        include_card_back=card_back,
    )

    write_manifest(cards, manifest, image_paths)

    tqdm.write("\nDone.")
    tqdm.write(f"PDF      : {output}")
    tqdm.write(f"Manifest : {manifest}")
    tqdm.write(f"Images   : {Path(args.image_dir).resolve()}")

    if args.duplex:
        tqdm.write(
            "\nDuplex note: print a small 9-card test first. "
            "Different printers flip the rear sheet differently. "
            "Try --back rotate180 or --back mirror if the backs are "
            "upside-down/misaligned."
        )

    return 0


# ----------------------------- argument parser ----------------------------


def build_parser():
    parser = argparse.ArgumentParser(
        description="Cockatrice XML -> printable A4 sheets"
    )

    sub = parser.add_subparsers(dest="command", required=True)

    def add_xml_dir(p):
        p.add_argument(
            "--xml-dir",
            default="xml",
            help="Directory containing downloaded XML files (default: xml)",
        )

    p = sub.add_parser("list", help="List XML files and their sets")
    add_xml_dir(p)
    p.set_defaults(func=cmd_list)

    p = sub.add_parser("sets", help="Alias for list")
    add_xml_dir(p)
    p.set_defaults(func=cmd_sets)

    p = sub.add_parser("validate", help="Validate XML and selected set")
    add_xml_dir(p)
    p.add_argument("--set", help="Set code, e.g. SOH or HCJ")
    p.set_defaults(func=cmd_validate)

    p = sub.add_parser("print", help="Create printable A4 PDF")
    add_xml_dir(p)

    p.add_argument(
        "--set",
        required=True,
        help="Set code to print, e.g. SOH, HCJ, NRM",
    )

    p.add_argument(
        "--names-file",
        help="Optional text file containing exact card names to print",
    )

    p.add_argument(
        "--exclude-tokens",
        action="store_true",
        help="Exclude cards whose Cockatrice layout is token",
    )

    p.add_argument(
        "--output-dir",
        default="output",
        help="Output directory (default: output)",
    )

    p.add_argument(
        "--output",
        help="PDF filename; default is <set>.pdf",
    )

    p.add_argument(
        "--image-dir",
        default="images",
        help="Image cache directory (default: images)",
    )

    p.add_argument(
        "--gap",
        type=float,
        default=DEFAULT_GAP_MM,
        help=f"Gap between cards in mm (default: {DEFAULT_GAP_MM})",
    )

    p.add_argument(
        "--margin",
        type=float,
        default=DEFAULT_MARGIN_MM,
        help=f"Minimum outer margin in mm (default: {DEFAULT_MARGIN_MM})",
    )

    p.add_argument(
        "--cut-style",
        choices=["none", "corners", "lines"],
        default="none",
        help="Cutting guides (default: none)",
    )

    p.add_argument(
        "--registration",
        action="store_true",
        help="Add printer registration marks near page corners",
    )

    p.add_argument(
        "--duplex",
        action="store_true",
        help="Append reverse-side pages for duplex printing",
    )

    p.add_argument(
        "--back",
        choices=["normal", "mirror", "rotate180"],
        default="normal",
        help="Transform duplex backs (default: normal)",
    )

    p.add_argument(
        "--card-back",
        help="Image to use for every reverse-side card",
    )

    p.add_argument(
        "--timeout",
        type=int,
        default=30,
        help="Image download timeout in seconds (default: 30)",
    )

    p.add_argument(
        "--retries",
        type=int,
        default=3,
        help="Image download attempts (default: 3)",
    )

    p.set_defaults(func=cmd_print)

    return parser


def main():
    print("--- Cockatrice Printer ---")
    parser = build_parser()
    args = parser.parse_args()

    try:
        return args.func(args)
    except KeyboardInterrupt:
        tqdm.write("\nInterrupted.", file=sys.stderr)
        return 130
    except Exception as exc:
        tqdm.write(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
