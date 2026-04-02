from __future__ import annotations

import argparse
import io
import re
import sys
from dataclasses import dataclass, fields
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING
from urllib.request import urlopen

if TYPE_CHECKING:
    from typing import Any

import yaml
from gtts import gTTS
from loguru import logger
from mutagen.id3 import APIC, ID3, TALB, TCON, TDRC, TIT2, TPE1, TRCK
from PIL import Image, ImageDraw, ImageFont
from pydub import AudioSegment

type WordPair = tuple[str, str]

FLAG_CACHE_DIR = Path(".cache/flags")


@dataclass(frozen=True)
class LessonConfig:
    language_1: str = "en"
    language_2: str = "pl"
    separator: str = " - "
    repeat_word: int = 2
    repeat_definition: int = 1
    pause_after_word_ms: int = 600
    pause_after_definition_ms: int = 1200
    pause_between_repeats_ms: int = 400
    speech_speed: str = "normal"
    output_dir: str = "outputs"

    @property
    def slow(self) -> bool:
        return self.speech_speed == "slow"


LOCAL_CONFIG_FILE = "config.local.yaml"


def _read_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return data if isinstance(data, dict) else {}


def load_config(path: Path) -> LessonConfig:
    base = _read_yaml(path)
    local = _read_yaml(path.parent / LOCAL_CONFIG_FILE)
    merged = {**base, **local}

    valid_keys = {f.name for f in fields(LessonConfig)}
    filtered = {k: v for k, v in merged.items() if k in valid_keys}
    return LessonConfig(**filtered)


def parse_words(path: Path, separator: str) -> list[WordPair]:
    pairs: list[WordPair] = []
    for lineno, raw_line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if separator not in line:
            logger.warning("Line {} skipped (no separator '{}'): {}", lineno, separator, line)
            continue
        word, definition = line.split(separator, maxsplit=1)
        pairs.append((word.strip(), definition.strip()))
    return pairs


def tts_to_segment(text: str, lang: str, *, slow: bool) -> AudioSegment:
    buf = io.BytesIO()
    gTTS(text=text, lang=lang, slow=slow).write_to_fp(buf)
    buf.seek(0)
    return AudioSegment.from_mp3(buf)


def _append_repeated(
    lesson: AudioSegment,
    segment: AudioSegment,
    repeats: int,
    pause_between: AudioSegment,
    pause_after: AudioSegment,
) -> AudioSegment:
    for r in range(repeats):
        lesson += segment
        if r < repeats - 1:
            lesson += pause_between
    return lesson + pause_after


def build_lesson(pairs: list[WordPair], config: LessonConfig) -> AudioSegment:
    pause_word = AudioSegment.silent(duration=config.pause_after_word_ms)
    pause_def = AudioSegment.silent(duration=config.pause_after_definition_ms)
    pause_rep = AudioSegment.silent(duration=config.pause_between_repeats_ms)

    lesson = AudioSegment.empty()

    for i, (word, definition) in enumerate(pairs, start=1):
        logger.info("[{}/{}] {} → {}", i, len(pairs), word, definition)

        word_seg = tts_to_segment(word, config.language_1, slow=config.slow)
        def_seg = tts_to_segment(definition, config.language_2, slow=config.slow)
        lesson = _append_repeated(lesson, def_seg, config.repeat_definition, pause_rep, pause_def)
        lesson = _append_repeated(lesson, word_seg, config.repeat_word, pause_rep, pause_word)

    return lesson


# ── Flag / cover helpers ──────────────────────────────────────────────

LANG_NAMES: dict[str, str] = {
    "en": "English",
    "pl": "Polish",
    "de": "German",
    "fr": "French",
    "es": "Spanish",
    "it": "Italian",
    "pt": "Portuguese",
    "ja": "Japanese",
    "ko": "Korean",
    "zh-CN": "Chinese",
    "uk": "Ukrainian",
    "nl": "Dutch",
    "sv": "Swedish",
    "cs": "Czech",
}

LANG_TO_COUNTRY: dict[str, str] = {
    "en": "gb",
    "pl": "pl",
    "de": "de",
    "fr": "fr",
    "es": "es",
    "it": "it",
    "pt": "pt",
    "ja": "jp",
    "ko": "kr",
    "zh-CN": "cn",
    "uk": "ua",
    "nl": "nl",
    "sv": "se",
    "cs": "cz",
}


def _lang_label(code: str) -> str:
    return LANG_NAMES.get(code, code)


def _download_flag(country_code: str) -> Path:
    FLAG_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    flag_path = FLAG_CACHE_DIR / f"{country_code}.png"
    if flag_path.exists():
        return flag_path
    url = f"https://flagcdn.com/w320/{country_code}.png"
    with urlopen(url, timeout=10) as resp:  # noqa: S310
        flag_path.write_bytes(resp.read())
    logger.info("Downloaded flag: {}", country_code)
    return flag_path


def _load_font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    for name in ("Arial.ttf", "Helvetica.ttc", "DejaVuSans.ttf", "LiberationSans-Regular.ttf"):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default(size=size)


def generate_cover(config: LessonConfig, output_dir: Path) -> Path:
    cover_path = output_dir / "cover.png"

    c1 = LANG_TO_COUNTRY.get(config.language_1, config.language_1[:2])
    c2 = LANG_TO_COUNTRY.get(config.language_2, config.language_2[:2])

    flag1 = Image.open(_download_flag(c1))
    flag2 = Image.open(_download_flag(c2))

    canvas_size = 600
    flag_w, flag_h = 200, 133
    flag1 = flag1.resize((flag_w, flag_h), Image.Resampling.LANCZOS)
    flag2 = flag2.resize((flag_w, flag_h), Image.Resampling.LANCZOS)

    img = Image.new("RGB", (canvas_size, canvas_size), color=(26, 26, 46))

    gap = 40
    total_w = flag_w * 2 + gap
    x1 = (canvas_size - total_w) // 2
    x2 = x1 + flag_w + gap
    y = canvas_size // 2 - flag_h // 2 - 40

    img.paste(flag1, (x1, y))
    img.paste(flag2, (x2, y))

    draw = ImageDraw.Draw(img)

    border = 2
    border_color = (70, 70, 100)
    draw.rectangle(
        (x1 - border, y - border, x1 + flag_w + border, y + flag_h + border),
        outline=border_color,
        width=border,
    )
    draw.rectangle(
        (x2 - border, y - border, x2 + flag_w + border, y + flag_h + border),
        outline=border_color,
        width=border,
    )

    arrow_cx = canvas_size // 2
    arrow_cy = y + flag_h // 2
    draw.line([(arrow_cx - 16, arrow_cy), (arrow_cx + 10, arrow_cy)], fill="white", width=3)
    draw.polygon([(arrow_cx + 18, arrow_cy), (arrow_cx + 8, arrow_cy - 8), (arrow_cx + 8, arrow_cy + 8)], fill="white")

    font_large = _load_font(28)
    font_small = _load_font(18)

    label = f"{_lang_label(config.language_1)}  →  {_lang_label(config.language_2)}"
    draw.text((canvas_size // 2, y + flag_h + 45), label, fill="white", anchor="mt", font=font_large)
    draw.text(
        (canvas_size // 2, y + flag_h + 85),
        "Voice Flashcards",
        fill=(130, 130, 160),
        anchor="mt",
        font=font_small,
    )

    img.save(cover_path, "PNG")
    logger.info("Cover saved: {}", cover_path)
    return cover_path


# ── ID3 tags ──────────────────────────────────────────────────────────


def _extract_track_number(stem: str) -> str | None:
    match = re.search(r"(\d+)", stem)
    return match.group(1) if match else None


def _write_id3_tags(
    mp3_path: Path,
    input_path: Path,
    config: LessonConfig,
    *,
    word_count: int,
    cover_path: Path | None,
) -> None:
    lesson_name = input_path.stem.replace("_", " ").title()
    lang_pair = f"{_lang_label(config.language_1)} → {_lang_label(config.language_2)}"
    year = datetime.now(tz=UTC).strftime("%Y")

    tags = ID3(mp3_path)
    tags.add(TIT2(encoding=3, text=f"{lesson_name} ({word_count} words)"))
    tags.add(TPE1(encoding=3, text="Voice Flashcards"))
    tags.add(TALB(encoding=3, text=lang_pair))
    tags.add(TCON(encoding=3, text="Education"))
    tags.add(TDRC(encoding=3, text=year))

    track = _extract_track_number(input_path.stem)
    if track:
        tags.add(TRCK(encoding=3, text=track))

    if cover_path and cover_path.exists():
        tags.add(APIC(encoding=3, mime="image/png", type=3, desc="Cover", data=cover_path.read_bytes()))

    tags.save()

    logger.info("ID3 tags: title={}, album={}, track={}", tags["TIT2"], tags["TALB"], track or "—")


# ── Processing ────────────────────────────────────────────────────────


def _resolve_output_path(input_path: Path, output_dir: Path) -> Path:
    return output_dir / input_path.with_suffix(".mp3").name


def _collect_input_files(input_path: Path) -> list[Path]:
    if input_path.is_file():
        return [input_path]
    if input_path.is_dir():
        files = sorted(f for f in input_path.iterdir() if f.is_file() and not f.name.startswith("."))
        if not files:
            logger.error("No files found in directory: {}", input_path)
            sys.exit(1)
        return files
    logger.error("Path does not exist: {}", input_path)
    sys.exit(1)


def process_file(
    input_path: Path,
    config: LessonConfig,
    output_dir: Path,
    *,
    cover_path: Path | None,
    output_override: Path | None = None,
) -> None:
    output_path = output_override or _resolve_output_path(input_path, output_dir)

    if output_path.exists():
        logger.info("Skipping {} (already exists: {})", input_path.name, output_path)
        return

    logger.info("Input:  {}", input_path)
    logger.info("Output: {}", output_path)

    pairs = parse_words(input_path, config.separator)
    if not pairs:
        logger.error("No word pairs found in {}. Skipping.", input_path)
        return

    logger.info("Found {} word pair(s). Generating audio...", len(pairs))
    lesson = build_lesson(pairs, config)

    fmt = output_path.suffix.lstrip(".") or "mp3"
    lesson.export(str(output_path), format=fmt)

    if fmt == "mp3":
        _write_id3_tags(output_path, input_path, config, word_count=len(pairs), cover_path=cover_path)

    duration_s = len(lesson) / 1000
    logger.success("Done! {} ({:.1f}s)\n", output_path, duration_s)


def main() -> None:
    logger.remove()
    logger.add(sys.stderr, format="<level>{message}</level>", level="INFO")

    parser = argparse.ArgumentParser(description="Generate audio lessons from word lists.")
    parser.add_argument("input", nargs="?", default="words.txt", help="Path to a word list file or directory")
    parser.add_argument("-c", "--config", default="config.yaml", help="Path to YAML config file")
    parser.add_argument("-o", "--output", help="Output file path (single file input only)")
    args = parser.parse_args()

    config = load_config(Path(args.config))
    input_path = Path(args.input)

    output_override = Path(args.output) if args.output else None
    output_dir = output_override.parent if output_override else Path(config.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    logger.info("Config:    {}", args.config)
    logger.info("Languages: {} → {}", config.language_1, config.language_2)
    logger.info("Output:    {}/\n", output_dir)

    input_files = _collect_input_files(input_path)

    if args.output and len(input_files) > 1:
        logger.error("Option -o cannot be used with directory input (multiple files).")
        sys.exit(1)

    cover_path = generate_cover(config, output_dir)

    for i, file in enumerate(input_files):
        if len(input_files) > 1:
            logger.info("━━━ [{}/{}] {} ━━━", i + 1, len(input_files), file.name)
        process_file(file, config, output_dir, cover_path=cover_path, output_override=output_override)

    if len(input_files) > 1:
        logger.success("All done! Processed {} file(s).", len(input_files))


if __name__ == "__main__":
    main()
