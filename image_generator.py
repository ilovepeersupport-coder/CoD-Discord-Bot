"""
Call of Duty League Match Graphic Generator
Generates a broadcast-quality match summary graphic (PNG) using Pillow.
Displays series results, player averages, K/D ratios, and MVP highlight.
"""
import io
import os
from typing import Dict, Any, List
from PIL import Image, ImageDraw, ImageFont

_BOLD_FONTS = (
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
    "/usr/share/fonts/truetype/liberation2/LiberationSans-Bold.ttf",
    r"C:\Windows\Fonts\segoeuib.ttf",
    r"C:\Windows\Fonts\arialbd.ttf",
)
_REGULAR_FONTS = (
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
    "/usr/share/fonts/truetype/liberation2/LiberationSans-Regular.ttf",
    r"C:\Windows\Fonts\segoeui.ttf",
    r"C:\Windows\Fonts\arial.ttf",
)


def _short(value, limit: int) -> str:
    text = " ".join(str(value or "").split())
    if len(text) <= limit:
        return text
    return text[: limit - 1] + "…"


def _as_int(value, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _as_float(value, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


class GraphicGenerator:
    """Creates esports-style match summary infographics."""

    @staticmethod
    def _load_font(font_name: str, size: int) -> ImageFont.ImageFont:
        """Load DejaVu (Linux/Docker), then Windows fonts, then Pillow's default."""
        bold = font_name.lower() in {"segoeuib", "arialbd", "bold"}
        font_paths = list(_BOLD_FONTS if bold else _REGULAR_FONTS)
        font_paths.extend([
            rf"C:\Windows\Fonts\{font_name}.ttf",
            rf"C:\Windows\Fonts\{font_name.lower()}.ttf",
            f"/usr/share/fonts/truetype/{font_name}.ttf",
            f"{font_name}.ttf",
        ])
        for path in font_paths:
            if os.path.exists(path):
                try:
                    return ImageFont.truetype(path, size)
                except OSError:
                    continue
        try:
            return ImageFont.load_default(size=size)
        except TypeError:
            return ImageFont.load_default()

    @classmethod
    def generate_series_card(cls, series_data: Dict[str, Any], series_title: str = "CALL OF DUTY LEAGUE SERIES") -> io.BytesIO:
        """
        Generates a 1200x800+ summary card image buffer.
        """
        players: List[Dict[str, Any]] = series_data.get("players", [])
        mvp = series_data.get("mvp")
        team_wins = series_data.get("team_wins", {})
        maps_summary = series_data.get("maps_summary", [])

        # Dimensions
        row_height = 42
        table_start_y = 310
        total_rows = max(len(players), 4)
        img_width = 1200
        img_height = table_start_y + (total_rows * row_height) + 120

        # Colors
        bg_color = (15, 20, 28)          # Deep tactical slate
        card_bg = (23, 30, 42)           # Card fill
        accent_cyan = (0, 210, 255)      # Call of Duty Cyan
        accent_gold = (245, 166, 35)     # Gold for MVP
        text_white = (245, 245, 250)
        text_dim = (140, 155, 175)
        text_green = (75, 215, 120)
        text_red = (245, 85, 85)
        line_color = (40, 52, 70)
        row_alt = (28, 37, 52)

        # Fonts
        font_title = cls._load_font("segoeuib", 32)
        font_subtitle = cls._load_font("segoeui", 18)
        font_score = cls._load_font("segoeuib", 42)
        font_header = cls._load_font("segoeuib", 16)
        font_body = cls._load_font("segoeui", 16)
        font_bold = cls._load_font("segoeuib", 16)
        font_badge = cls._load_font("segoeuib", 13)

        image = Image.new("RGB", (img_width, img_height), color=bg_color)
        draw = ImageDraw.Draw(image)

        # Top Accent Header Bar
        draw.rectangle([0, 0, img_width, 6], fill=accent_cyan)

        # Series Title
        draw.text((50, 28), _short(series_title.upper(), 42), fill=text_white, font=font_title)

        # Map list / mode subtitle
        maps_str = "  |  ".join([
            f"M{m.get('map_number')}: {m.get('map_name')} ({m.get('game_mode')})"
            for m in maps_summary if isinstance(m, dict)
        ])
        if not maps_str:
            maps_str = f"Series of {len(maps_summary)} Maps"
        draw.text((50, 72), _short(maps_str, 110), fill=text_dim, font=font_subtitle)

        # Team Score Box (Top Right or Center)
        team_names = list(team_wins.keys())
        if len(team_names) >= 2:
            t1, t2 = _short(team_names[0], 18), _short(team_names[1], 18)
            s1, s2 = team_wins.get(team_names[0], 0), team_wins.get(team_names[1], 0)
            score_text = f"{t1}  {s1} - {s2}  {t2}"
        elif len(team_names) == 1:
            score_text = f"{team_names[0]} ({team_wins.get(team_names[0], 0)} Wins)"
        else:
            score_text = f"{len(maps_summary)} MAPS PLAYED"

        # Dynamically scale score font if text is long
        if len(score_text) > 30:
            font_score = cls._load_font("segoeuib", 28)
        elif len(score_text) > 22:
            font_score = cls._load_font("segoeuib", 34)
        else:
            font_score = cls._load_font("segoeuib", 42)

        # MVP Showcase Box (Left)
        if mvp:
            mvp_box_x = 50
            mvp_box_y = 115
            mvp_box_w = 420
            mvp_box_h = 150

            # Card background
            draw.rectangle([mvp_box_x, mvp_box_y, mvp_box_x + mvp_box_w, mvp_box_y + mvp_box_h], fill=card_bg, outline=line_color, width=1)
            # Gold MVP ribbon
            draw.rectangle([mvp_box_x, mvp_box_y, mvp_box_x + 6, mvp_box_y + mvp_box_h], fill=accent_gold)
            draw.rectangle([mvp_box_x + 18, mvp_box_y + 12, mvp_box_x + 130, mvp_box_y + 34], fill=accent_gold)
            draw.text((mvp_box_x + 28, mvp_box_y + 14), "SERIES MVP", fill=(10, 10, 15), font=font_badge)

            # MVP Name & Team
            mvp_name = _short(mvp.get("name", "Unknown"), 18)
            mvp_team = _short(mvp.get("team", ""), 28)
            draw.text((mvp_box_x + 20, mvp_box_y + 44), mvp_name, fill=text_white, font=font_title)
            if mvp_team:
                draw.text((mvp_box_x + 20, mvp_box_y + 82), f"Team: {mvp_team}", fill=accent_cyan, font=font_subtitle)

            # Keep this on one line inside the 420px MVP card.
            mvp_stats_str = (
                f"K/D {_as_float(mvp.get('kd')):.2f}   "
                f"Avg K {mvp.get('avg_kills', 0)}   "
                f"Dmg {_as_int(mvp.get('damage')):,}"
            )
            draw.text((mvp_box_x + 20, mvp_box_y + 114), mvp_stats_str, fill=text_dim, font=font_body)

        # Series Score Showcase Box (Right)
        score_box_x = 490
        score_box_y = 115
        score_box_w = 660
        score_box_h = 150
        draw.rectangle([score_box_x, score_box_y, score_box_x + score_box_w, score_box_y + score_box_h], fill=card_bg, outline=line_color, width=1)
        draw.rectangle([score_box_x, score_box_y, score_box_x + 6, score_box_y + score_box_h], fill=accent_cyan)

        draw.text((score_box_x + 24, score_box_y + 16), "MATCH RESULT", fill=accent_cyan, font=font_badge)
        draw.text((score_box_x + 24, score_box_y + 50), score_text.upper(), fill=text_white, font=font_score)

        # Leader stats line
        top_k = series_data.get("top_kills")
        top_dmg = series_data.get("top_damage")
        leaders_line = []
        if top_k:
            leaders_line.append(f"Most Kills: {_short(top_k.get('name'), 16)} ({_as_int(top_k.get('kills'))})")
        if top_dmg:
            leaders_line.append(f"Most Damage: {_short(top_dmg.get('name'), 16)} ({_as_int(top_dmg.get('damage')):,})")
        draw.text((score_box_x + 24, score_box_y + 114), "  |  ".join(leaders_line), fill=text_dim, font=font_header)

        # STATS TABLE
        # Column definitions (Name, X position, Width, Alignment)
        columns = [
            ("PLAYER", 70, "left"),
            ("TEAM", 240, "left"),
            ("MAPS", 360, "center"),
            ("K", 440, "center"),
            ("D", 500, "center"),
            ("+/-", 570, "center"),
            ("K/D", 650, "center"),
            ("AVG K", 740, "center"),
            ("AVG D", 830, "center"),
            ("DAMAGE", 930, "right"),
            ("AVG DMG", 1040, "right"),
        ]

        # Draw Table Header
        header_y = table_start_y
        draw.rectangle([50, header_y, img_width - 50, header_y + 36], fill=card_bg)
        draw.line([50, header_y + 36, img_width - 50, header_y + 36], fill=accent_cyan, width=2)

        for col_name, col_x, align in columns:
            draw.text((col_x, header_y + 8), col_name, fill=text_dim, font=font_header)

        # Draw Table Rows
        curr_y = header_y + 40
        for idx, p in enumerate(players):
            # Alternating background
            if idx % 2 == 1:
                draw.rectangle([50, curr_y, img_width - 50, curr_y + row_height], fill=row_alt)

            # Player name with MVP crown/badge if applicable
            p_name = _short(p.get("name", "Player"), 16)
            if mvp and p.get("name") == mvp.get("name"):
                draw.text((70, curr_y + 10), f"[MVP] {_short(p_name, 12)}", fill=accent_gold, font=font_bold)
            else:
                draw.text((70, curr_y + 10), p_name, fill=text_white, font=font_bold)

            # Team
            draw.text((240, curr_y + 10), _short(p.get("team", "-"), 14), fill=text_dim, font=font_body)

            # Maps
            draw.text((370, curr_y + 10), str(p.get("maps_played", 1)), fill=text_white, font=font_body)

            # Kills
            draw.text((445, curr_y + 10), str(p.get("kills", 0)), fill=text_white, font=font_body)

            # Deaths
            draw.text((505, curr_y + 10), str(p.get("deaths", 0)), fill=text_white, font=font_body)

            # +/- Differential
            diff = _as_int(p.get("plus_minus", 0))
            diff_str = f"+{diff}" if diff > 0 else str(diff)
            diff_color = text_green if diff > 0 else (text_red if diff < 0 else text_dim)
            draw.text((575, curr_y + 10), diff_str, fill=diff_color, font=font_bold)

            # K/D Ratio
            kd = _as_float(p.get("kd"), 1.0)
            kd_str = f"{kd:.2f}"
            kd_color = text_green if kd >= 1.0 else text_red
            draw.text((655, curr_y + 10), kd_str, fill=kd_color, font=font_bold)

            # Avg Kills
            draw.text((750, curr_y + 10), str(p.get("avg_kills", 0.0)), fill=text_white, font=font_body)

            # Avg Deaths
            draw.text((840, curr_y + 10), str(p.get("avg_deaths", 0.0)), fill=text_white, font=font_body)

            # Total Damage
            draw.text((930, curr_y + 10), f"{_as_int(p.get('damage', 0)):,}", fill=text_white, font=font_body)

            # Avg Damage
            draw.text((1040, curr_y + 10), f"{_as_float(p.get('avg_damage', 0)):,.0f}", fill=accent_cyan, font=font_bold)

            # Bottom separator line
            draw.line([50, curr_y + row_height, img_width - 50, curr_y + row_height], fill=line_color, width=1)
            curr_y += row_height

        # Footer
        footer_y = curr_y + 20
        draw.text((50, footer_y), "Auto-generated by Call of Duty League Stats Bot", fill=text_dim, font=font_subtitle)
        draw.text((img_width - 320, footer_y), "Black Ops 6 / Modern Warfare III", fill=text_dim, font=font_subtitle)

        # Output to buffer
        buffer = io.BytesIO()
        image.save(buffer, format="PNG")
        buffer.seek(0)
        return buffer
