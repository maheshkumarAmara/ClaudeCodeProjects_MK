"""Forces every email address printed in a generated PDF onto the sandbox domain.

sandbox_email.sandbox_fields only covers the form's field values. A template
also prints addresses as static text (header "Email:" lines, footers, address
blocks), and where a generator whiteouts a template value and draws its own on
top, the real address stays in the PDF's text layer underneath. This rewrites
the page content streams instead: every text-showing operation whose text holds
a non-sandbox address is replaced, in the same place in the stream, by that
text on the sandbox domain -- so the real address is gone from the visible page
and from the text layer alike. mailto: link annotations are rewritten too.

Known limitations:
  - Replaced text is drawn in Helvetica rather than the template's font.
  - An address split across two separate text operations is not detected.
"""

import io
import re

from pypdf import PdfReader, PdfWriter
from pypdf.generic import ContentStream, DictionaryObject, FloatObject, NameObject, TextStringObject
from reportlab.pdfbase.pdfmetrics import stringWidth

from sandbox_email import sandbox_text

_FONT_KEY = NameObject("/SandboxEmailFont")
_FONT_DICT = {
    NameObject("/Type"): NameObject("/Font"),
    NameObject("/Subtype"): NameObject("/Type1"),
    NameObject("/BaseFont"): NameObject("/Helvetica"),
    NameObject("/Encoding"): NameObject("/WinAnsiEncoding"),
}
_STANDARD_FONTS = {
    "Helvetica", "Helvetica-Bold", "Helvetica-Oblique", "Helvetica-BoldOblique",
    "Times-Roman", "Times-Bold", "Times-Italic", "Times-BoldItalic",
    "Courier", "Courier-Bold", "Courier-Oblique", "Courier-BoldOblique",
}
_HEX_RE = re.compile(r"<([0-9A-Fa-f]+)>")


def _parse_to_unicode(cmap: str) -> dict[int, str]:
    mapping: dict[int, str] = {}

    def decode(hex_text: str) -> str:
        return bytes.fromhex(hex_text).decode("utf-16-be")

    for block in re.findall(r"beginbfchar(.*?)endbfchar", cmap, re.S):
        for src, dst in re.findall(r"<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]+)>", block):
            mapping[int(src, 16)] = decode(dst)
    for block in re.findall(r"beginbfrange(.*?)endbfrange", cmap, re.S):
        for lo, hi, dst in re.findall(r"<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]+)>\s*(<[0-9A-Fa-f]+>|\[[^\]]*\])", block):
            codes = range(int(lo, 16), int(hi, 16) + 1)
            if dst.startswith("["):
                for code, target in zip(codes, _HEX_RE.findall(dst)):
                    mapping[code] = decode(target)
            else:
                first = decode(dst[1:-1])
                for offset, code in enumerate(codes):
                    mapping[code] = first[:-1] + chr(ord(first[-1]) + offset)
    return mapping


class _Decoder:
    """Turns a font's string operands back into text; None when it can't."""

    def __init__(self, font) -> None:
        font = font.get_object()
        self.width = 2 if font.get("/Subtype") == "/Type0" else 1
        self.mapping = None
        if "/ToUnicode" in font:
            data = font["/ToUnicode"].get_object().get_data()
            self.mapping = _parse_to_unicode(data.decode("latin-1"))
        self.usable = self.mapping is not None or self.width == 1
        self._widths = self._load_widths(font)
        # Standard fonts (Helvetica, Courier, ...) carry no /Widths; reportlab has their metrics.
        base = str(font.get("/BaseFont", "")).lstrip("/")
        self._standard = base if base in _STANDARD_FONTS and not self._widths[0] else None

    def _load_widths(self, font):
        """code -> glyph width in 1/1000 em, plus the default for unlisted codes."""
        table: dict[int, float] = {}
        if self.width == 2:
            cid = font["/DescendantFonts"].get_object()[0].get_object()
            default = float(cid.get("/DW", 1000))
            widths = cid["/W"].get_object() if "/W" in cid else []
            i = 0
            while i < len(widths):
                first = widths[i]
                nxt = widths[i + 1].get_object() if i + 1 < len(widths) else None
                if isinstance(nxt, list):
                    for offset, w in enumerate(nxt):
                        table[int(first) + offset] = float(w)
                    i += 2
                else:
                    for code in range(int(first), int(nxt) + 1):
                        table[code] = float(widths[i + 2])
                    i += 3
            return table, default
        first_char = int(font.get("/FirstChar", 0))
        widths = font["/Widths"].get_object() if "/Widths" in font else []
        for offset, w in enumerate(widths):
            table[first_char + offset] = float(w)
        descriptor = font.get("/FontDescriptor")
        default = float(descriptor.get_object().get("/MissingWidth", 0)) if descriptor is not None else 0.0
        return table, default

    def text_width(self, raw: bytes) -> float:
        """Printed width of the string in 1/1000 em (before font size / spacing)."""
        if self._standard:
            return stringWidth(raw.decode("latin-1"), self._standard, 1000)
        table, default = self._widths
        return sum(
            table.get(int.from_bytes(raw[i : i + self.width], "big"), default)
            for i in range(0, len(raw), self.width)
        )

    def decode(self, raw: bytes) -> str:
        if self.mapping is None:
            return raw.decode("latin-1")
        return "".join(
            self.mapping.get(int.from_bytes(raw[i : i + self.width], "big"), "")
            for i in range(0, len(raw), self.width)
        )


def _sandbox_container(container, resources, writer, seen: set[int], replace=sandbox_text) -> None:
    """Rewrite the content stream of a page or form XObject (and the forms it draws).

    replace(text) -> text decides what each text-showing operation becomes; text it returns
    unchanged is left alone."""
    fonts = resources.get("/Font")
    fonts = fonts.get_object() if fonts is not None else {}
    xobjects = resources.get("/XObject")
    xobjects = xobjects.get_object() if xobjects is not None else {}
    decoders: dict[str, _Decoder] = {}

    def decoder_for(name):
        if name not in decoders:
            decoders[name] = _Decoder(fonts[name]) if name in fonts else None
        return decoders[name]

    is_page = hasattr(container, "replace_contents")
    stream = container.get_contents() if is_page else container
    if stream is None:
        return
    content = ContentStream(stream, writer)
    operations = []
    stack: list[tuple] = []
    font_name, font_size = None, None
    replaced = False
    for operands, operator in content.operations:
        if operator == b"q":
            stack.append((font_name, font_size))
        elif operator == b"Q" and stack:
            font_name, font_size = stack.pop()
        elif operator == b"Tf":
            font_name, font_size = operands[0], operands[1]
        elif operator == b"Do" and operands[0] in xobjects:
            form = xobjects[operands[0]].get_object()
            ref = getattr(form, "indirect_reference", None)
            if form.get("/Subtype") == "/Form" and (ref is None or ref.idnum not in seen):
                if ref is not None:
                    seen.add(ref.idnum)
                _sandbox_container(form, form.get("/Resources") or resources, writer, seen, replace)
        elif operator in (b"Tj", b"TJ") and font_name is not None:
            dec = decoder_for(font_name)
            if dec is not None and dec.usable:
                parts = [operands[0]] if operator == b"Tj" else [o for o in operands[0] if hasattr(o, "original_bytes")]
                text = "".join(dec.decode(part.original_bytes) for part in parts)
                safe = replace(text)
                if safe != text:
                    # Same place in the stream, so the text state (position, colour,
                    # spacing) carries over; only the font is swapped for one line.
                    # The sandbox domain can be longer than the one it replaces, and
                    # a generator may have covered the original with a box sized for
                    # it, so squeeze the replacement to the original's printed width.
                    original_width = sum(dec.text_width(part.original_bytes) for part in parts)
                    new_width = stringWidth(safe, "Helvetica", 1000)
                    scale = 100.0 * original_width / new_width if original_width and new_width else 100.0
                    squeeze = scale < 100.0
                    operations.append(([_FONT_KEY, font_size], b"Tf"))
                    if squeeze:
                        operations.append(([FloatObject(round(scale, 2))], b"Tz"))
                    operations.append(([TextStringObject(safe.encode("cp1252", "replace").decode("latin-1"))], b"Tj"))
                    if squeeze:
                        operations.append(([FloatObject(100)], b"Tz"))
                    operations.append(([font_name, font_size], b"Tf"))
                    replaced = True
                    continue
        operations.append((operands, operator))

    if not replaced:
        return
    content.operations = operations
    if is_page:
        container.replace_contents(content)
    else:
        container.set_data(content.get_data())
    if "/Font" not in resources:
        resources[NameObject("/Font")] = DictionaryObject()
    resources["/Font"].get_object()[_FONT_KEY] = DictionaryObject(_FONT_DICT)


def _sandbox_links(page, replace=sandbox_text) -> None:
    for annot in page.get("/Annots") or []:
        action = annot.get_object().get("/A")
        action = action.get_object() if action is not None else None
        if action is not None and "/URI" in action:
            action[NameObject("/URI")] = TextStringObject(replace(str(action["/URI"])))


def rewrite_pdf_text(pdf_bytes: bytes, replace=sandbox_text, on_page=None, write: bool = True) -> bytes | None:
    """Run replace over every text-showing operation and mailto: link of the PDF.

    on_page(number) is called (1-based) before each page is processed, so a replace that only
    records what it sees can tell which page the text is on. With write=False nothing is
    serialised and None is returned (a read-only scan)."""
    writer = PdfWriter(clone_from=PdfReader(io.BytesIO(pdf_bytes)))
    seen: set[int] = set()
    for number, page in enumerate(writer.pages, start=1):
        if on_page is not None:
            on_page(number)
        resources = page.get("/Resources")
        if resources is None:
            continue
        _sandbox_container(page, resources.get_object(), writer, seen, replace)
        _sandbox_links(page, replace)
    if not write:
        return None
    output = io.BytesIO()
    writer.write(output)
    return output.getvalue()


def sandbox_pdf_emails(pdf_bytes: bytes) -> bytes:
    return rewrite_pdf_text(pdf_bytes)
