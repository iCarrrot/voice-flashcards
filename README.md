# Voice Flashcards

Generate audio lessons from word lists — each word and its translation are read aloud using Google TTS. Output MP3 files include ID3 metadata and an auto-generated album cover with language flags.

## Setup

```bash
uv sync
brew install ffmpeg   # macOS — required by pydub for mp3 export
```

## Usage

### Single file

```bash
uv run python generate.py inputs/lesson_1
```

Generates `outputs/lesson_1.mp3` (output directory is set in `config.yaml`).

### Entire directory

```bash
uv run python generate.py inputs/
```

Processes all files in the folder. Already generated MP3s are skipped automatically.

### Options

```bash
uv run python generate.py inputs/lesson_5 -o custom_path/out.mp3   # custom output path
uv run python generate.py inputs/ -c my_config.yaml                # custom config
```

## Input format

One word pair per line, separated by the configured separator (default ` - `):

```
apple - jabłko
house - dom
water - woda
```

Lines starting with `#` and empty lines are ignored.

## Configuration

All settings live in `config.yaml`:

```yaml
language_1: en          # source language (BCP-47 code)
language_2: pl          # target language
separator: " - "        # delimiter between word and definition
repeat_word: 2          # how many times each word is spoken
repeat_definition: 1    # how many times each definition is spoken
pause_after_word_ms: 800
pause_after_definition_ms: 1200
pause_between_repeats_ms: 600
output_dir: outputs     # where MP3 files are saved
speech_speed: slow      # "slow" or "normal"
```

## Output

- MP3 files in `output_dir/`, named after the input file
- `cover.png` — album cover with language flags, embedded in every MP3
- ID3 tags: title, artist, album (language pair), genre, year, track number
