"""Estimates how wide text renders in a Discord message, in pixels.

Discord draws messages in its "gg sans" font. gg_sans_metrics.json has each character's
width and the kerning between ASCII pairs, measured in Discord's web client by
measure_gg_sans.js (run it again if Discord changes its font), and the sizes below come
from Discord's CSS. Widths are for the default chat font scaling (16px text) and 100% zoom,
and match the browser's layout to within about half a pixel; pass font_size for other scalings.

line_width understands custom and unicode emojis, **bold**, `inline code`, and lines
starting with '# ', '## ', '### ' or '-# '. Other markdown is measured as plain text,
and so are mentions, since their names aren't known here.

padding gives whitespace of a given width, for lining text up in columns.
"""

import json
import re
import unicodedata
from functools import cache
from pathlib import Path

METRICS_FILE = Path(__file__).with_name('gg_sans_metrics.json')

FONT_SIZE = 16  # px, message text at the default chat font scaling (1rem)
# px at 100% zoom: the widest line known to fit without wrapping in a voice channel's chat,
# which opens in a narrow panel beside the call. Its width varies: two screenshots of /ow q
# there (2026-11-02) put it at 355-363px, and a later one (2026-11-05) at 338.4-352.2px.
CHAT_WIDTH = 338
EMOJI_SIZE = 1.375  # em, emojis next to text (Discord's --custom-emoji-size-emoji)
CODE_SCALE = 0.85  # `inline code` is 85% of the text's size, in gg mono
CODE_PADDING = 0.2  # em of the code's size, on each side
# Line prefixes that change the size (as a multiple of the text's) and weight of the whole line.
LINE_STYLES = (('# ', 1.5, True), ('## ', 1.25, True), ('### ', 1, True), ('-# ', 0.875, False))

UNITS_PER_EM = 1000  # gg_sans_metrics.json's widths are per 1000px of font size
REGULAR, BOLD = '400', '700'
# Characters that take no space of their own: joiners, variation selectors, soft hyphens.
ZERO_WIDTH = frozenset('​‌‍⁠︎️­')
ZWJ = '‍'

# Spaces padding() mixes in with normal ones: six-per-em and three-per-em, 1/6 and 1/3 of the font size. Their
# widths aren't whole numbers of normal spaces, so a mix lands much closer to a width than normal spaces alone.
# Three-per-em is exactly two six-per-em, so it only keeps the padding shorter. Of 16 Unicode spaces posted to
# Discord and measured (2026-11-05), only these two were the same width on desktop and iOS; the rest drew up
# to 97% off on iOS. Android wasn't checked.
SIX_PER_EM, THREE_PER_EM = ' ', ' '

# Pieces of a line drawn differently from the text around them: custom emojis, bold markers, inline code.
MARKUP = re.compile(r'(<a?:\w+:\d+>|\*\*|`[^`\n]+`)')


class _Font:
    """One weight of gg sans: character widths and kerning, in font units."""

    def __init__(self, metrics: dict, weight: str):
        # Widths are listed for ASCII, then Latin-1, then extra_chars (see gg_sans_metrics.json).
        chars = [chr(code) for code in (*range(32, 127), *range(0xA0, 0x100))] + list(metrics['extra_chars'])
        data = metrics['weights'][weight]
        self.widths: dict[str, int] = dict(zip(chars, data['widths']))
        self.kerning: dict[tuple[str, str], int] = {
            (left, right): int(amount)
            for left, by_amount in data['kerning'].items()
            for amount, rights in by_amount.items()
            for right in rights
        }
        self.mono_width: int = metrics['mono_width']

    def char_width(self, char: str) -> int:
        if char in self.widths:
            return self.widths[char]
        if unicodedata.east_asian_width(char) in ('W', 'F'):
            return UNITS_PER_EM  # CJK and other full-width characters are 1em in their fallback fonts
        return self.widths['n']  # A typical letter for anything else gg sans doesn't cover

@cache
def _font(weight: str) -> _Font:
    return _Font(json.loads(METRICS_FILE.read_text(encoding='utf-8')), weight)

def _is_emoji(char: str) -> bool:
    """Roughly whether Discord draws this character as an emoji image."""
    code = ord(char)
    return 0x1F000 <= code <= 0x1FAFF or 0x2600 <= code <= 0x27BF or 0x2B00 <= code <= 0x2BFF

def _text_units(text: str, font: _Font) -> float:
    """Width of plain text (no markdown) in font units, with kerning and emojis."""
    units = 0.0
    previous = ''
    for i, char in enumerate(text):
        code = ord(char)
        if char in ZERO_WIDTH or unicodedata.combining(char) or 0x1F3FB <= code <= 0x1F3FF:
            continue  # Skin tones and accents sit on the character before them
        if _is_emoji(char):
            if i and text[i - 1] == ZWJ:
                continue  # Joined onto the emoji before, e.g. a family
            # Flags are a pair of regional indicator letters drawn as one emoji.
            units += EMOJI_SIZE * UNITS_PER_EM / (2 if 0x1F1E6 <= code <= 0x1F1FF else 1)
            previous = ''
            continue
        units += font.char_width(char) + font.kerning.get((previous, char), 0)
        previous = char
    return units

def text_width(text: str, font_size: float = FONT_SIZE, bold: bool = False) -> float:
    """Pixel width of plain text, without markdown, e.g. one account name."""
    return _text_units(text, _font(BOLD if bold else REGULAR)) * font_size / UNITS_PER_EM

def line_width(line: str, font_size: float = FONT_SIZE) -> float:
    """Pixel width of one line of a message as Discord renders it, before it wraps.

    Args:
        line: The message text for one line, with Discord markdown and emoji markup like '<:diamond2:123>'.
        font_size: The chat text size in px; 16 at the default font scaling.
    """
    line_bold = False
    for prefix, scale, bold in LINE_STYLES:
        if line.startswith(prefix):
            line, font_size, line_bold = line[len(prefix):], font_size * scale, bold
            break

    pieces = MARKUP.split(line)  # Alternates text, markup, text, ...
    # '**' only makes bold in pairs; one left over is shown as it is.
    bold_markers = sum(1 for piece in pieces[1::2] if piece == '**')
    paired_markers = bold_markers - bold_markers % 2
    strong = False
    markers_seen = 0
    units = 0.0
    for i, piece in enumerate(pieces):
        font = _font(BOLD if line_bold or strong else REGULAR)
        if i % 2 == 0:
            units += _text_units(piece, font)
        elif piece == '**':
            markers_seen += 1
            if markers_seen <= paired_markers:
                strong = not strong
            else:
                units += _text_units(piece, font)
        elif piece.startswith('`'):
            code = piece[1:-1]
            units += CODE_SCALE * (len(code) * font.mono_width + 2 * CODE_PADDING * UNITS_PER_EM)
        else:
            units += EMOJI_SIZE * UNITS_PER_EM  # A custom emoji
    return units * font_size / UNITS_PER_EM

def line_widths(message: str, font_size: float = FONT_SIZE) -> list[float]:
    """line_width for each line of a message."""
    return [line_width(line, font_size) for line in message.split('\n')]

def padding(width: float, font_size: float = FONT_SIZE) -> str:
    """Whitespace as close as it can get to width px wide, for lining text up in columns (Discord keeps
    repeated spaces): normal spaces mixed with six-per-em and three-per-em ones, the fewest characters that
    get closest, and always at least one. Lands within 0.9px (on gaps barely wider than a space, where
    nothing narrower fits), and about a tenth of a pixel off on average."""
    space = text_width(' ', font_size)
    sixth = text_width(SIX_PER_EM, font_size)
    best, best_error = ' ', float('inf')
    # Try every count of six-per-em widths up to just past the width, filling the rest with normal spaces.
    # Each pair is written as one three-per-em.
    for sixths in range(int(width / sixth) + 2):
        spaces = max(0, round((width - sixths * sixth) / space))
        text = ' ' * spaces + THREE_PER_EM * (sixths // 2) + SIX_PER_EM * (sixths % 2)
        if not text:
            continue
        error = abs(text_width(text, font_size) - width)
        if error < best_error - 1e-6 or (error < best_error + 1e-6 and len(text) < len(best)):
            best, best_error = text, error
    return best
