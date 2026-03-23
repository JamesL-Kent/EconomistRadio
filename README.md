# Radio Agent

This project builds an always-on radio host service for narrated articles and podcast features. It scans a configured content folder, prioritises the latest day's work, blends in strong items from the week, occasionally pulls an older evergreen piece, generates very short host links, and publishes a rolling live audio stream.

## How it works

1. The service scans the configured content root for audio files.
2. For each audio file it loads optional sidecar metadata from a JSON or YAML file with the same stem.
3. The scheduler ranks candidates with a strong bias toward today's material, then injects weekly and archive features at configured intervals.
4. A host-link script is generated from the personality templates in [config/radio.example.yaml](/C:/Users/James/Documents/Code/The%20Economist/Radio/config/radio.example.yaml).
5. AWS Polly renders that short link to audio.
6. The link audio and source feature audio are stitched together, segmented, and written into a rolling HLS playlist.
7. The FastAPI app serves the live playlist and can optionally mirror the generated assets to S3 for AWS delivery.

## Source material

Point `content.root_path` at the folder that receives your narrated material. The default is [content/README.md](/C:/Users/James/Documents/Code/The%20Economist/Radio/content/README.md).

Expected layout:

```text
content/
  2026-03-20/
    markets-briefing.mp3
    markets-briefing.json
  2026-03-17/
    elections-roundup.mp3
    elections-roundup.yaml
  archive/
    industrial-policy-feature.mp3
    industrial-policy-feature.json
```

Sidecar metadata fields:

- `title`: Public title for the feature.
- `published_at`: ISO timestamp or date. If omitted, the system falls back to the parent folder date or file modified time.
- `section`: Used in host links such as "next, a quick shift into finance".
- `summary`: Short blurb used for the teaser sentence.
- `announcer_intro`: Optional override for the teaser fragment if you want a more controlled setup line.
- `interesting_score`: Number between `0.0` and `1.0`. Older items need this, or `evergreen: true`, to qualify as archive inserts.
- `evergreen`: Marks an older feature as valid archive material.
- `source_url`: Optional editorial reference.
- `duration_seconds`: Optional metadata hint.

Example metadata lives in [examples/content/2026-03-20/markets-briefing.json](/C:/Users/James/Documents/Code/The%20Economist/Radio/examples/content/2026-03-20/markets-briefing.json), [examples/content/2026-03-17/elections-roundup.json](/C:/Users/James/Documents/Code/The%20Economist/Radio/examples/content/2026-03-17/elections-roundup.json), and [examples/content/archive/industrial-policy-feature.json](/C:/Users/James/Documents/Code/The%20Economist/Radio/examples/content/archive/industrial-policy-feature.json).

## Personality configuration

The personality area is the `host:` block in [config/radio.example.yaml](/C:/Users/James/Documents/Code/The%20Economist/Radio/config/radio.example.yaml). That is where you control:

- Presenter name.
- Editorial identity and tone notes.
- TTS backend selection.
- Polly voice.
- Max word count and sentence count for links.
- Opener, bridge, and teaser template banks.
- Phrases the host must never use.

The current implementation is deliberately deterministic. It does not hide selection or copy choices behind an opaque LLM prompt. If you want a more free-form writer later, the clean extension point is [src/radio_agent/script_writer.py](/C:/Users/James/Documents/Code/The%20Economist/Radio/src/radio_agent/script_writer.py).

## Output hookup

The live output is written to [runtime/output](/C:/Users/James/Documents/Code/The%20Economist/Radio/runtime/output) and served at `/stream`.

- Playlist path on disk: [runtime/output/live.m3u8](/C:/Users/James/Documents/Code/The%20Economist/Radio/runtime/output/live.m3u8)
- Local stream URL: `/stream/live.m3u8`
- App status endpoint: `/status`
- Health endpoint: `/healthz`

If `output.s3_bucket` is set, every generated segment and the rolling playlist are mirrored to S3 as well. That makes it straightforward to front the stream with CloudFront while still allowing the app to run continuously in ECS, App Runner, or Fargate.

## Running in AWS

This repository includes [Dockerfile](/C:/Users/James/Documents/Code/The%20Economist/Radio/Dockerfile), which installs Python and `ffmpeg` into a deployable image.

Recommended AWS shape:

- Run the app as a single always-on container in ECS Fargate or App Runner.
- Store source audio on EFS or mount a synced content volume if the files arrive locally.
- Give the task IAM access to Polly, and to S3 if you enable stream mirroring.
- Put CloudFront in front of the service or the S3 mirror for public playback.
- Persist [runtime/state/radio.db](/C:/Users/James/Documents/Code/The%20Economist/Radio/runtime/state/radio.db) on durable storage if you want replay avoidance to survive task replacement.

## Local commands

Install dependencies:

```powershell
pip install -e .[dev]
```

Run the service:

```powershell
$env:RADIO_CONFIG_PATH="config/radio.example.yaml"
uvicorn radio_agent.main:app --host 0.0.0.0 --port 8000
```

Local development without AWS Polly:

- Set `host.tts_backend: silence` in [config/radio.example.yaml](/C:/Users/James/Documents/Code/The%20Economist/Radio/config/radio.example.yaml).
- The app will still build the stream and playlists, but host links will be short silent placeholders instead of spoken audio.

Run tests:

```bash
pytest
```

## Notes

- `ffmpeg` and `ffprobe` are runtime requirements.
- Windows hosts also need the Python `tzdata` package so `Europe/London` and other IANA timezones resolve correctly.
- AWS credentials must be available only when `host.tts_backend` is `polly`, and optionally for S3.
- The current workspace does not have Python or `ffmpeg` installed, so this repository was scaffolded and reviewed statically rather than executed here.
