"""Command line front-end: `dataconverter audio|image|video <files/folders> -f <format>`."""

from __future__ import annotations

import argparse
import sys

from . import audio, image, video


def _common(p: argparse.ArgumentParser, formats) -> None:
    p.add_argument("inputs", nargs="+", help="files or folders")
    p.add_argument("-f", "--format", required=True, choices=sorted(formats))
    p.add_argument("-o", "--output-dir")
    p.add_argument("--overwrite", action="store_true")
    p.add_argument("--no-recursive", action="store_true")
    p.add_argument("-j", "--jobs", type=int, default=2)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="dataconverter")
    sub = ap.add_subparsers(dest="cmd", required=True)

    a = sub.add_parser("audio", help="convert audio files")
    _common(a, audio.FORMATS)
    a.add_argument("-b", "--bitrate", help="e.g. 192k")
    a.add_argument("-r", "--sample-rate", type=int)
    a.add_argument("-c", "--channels", type=int, choices=(1, 2))
    a.add_argument("--no-metadata", action="store_true")

    i = sub.add_parser("image", help="convert images")
    _common(i, image.FORMATS)
    i.add_argument("-q", "--quality", type=int, default=90)
    i.add_argument("--max-width", type=int)
    i.add_argument("--max-height", type=int)

    v = sub.add_parser("video", help="convert videos")
    _common(v, video.FORMATS)
    v.add_argument("--crf", type=int, default=23, help="quality, lower is better")
    v.add_argument("--height", type=int, help="scale down to this height")
    v.add_argument("--fps", type=float)
    v.add_argument("--extract-audio", metavar="FORMAT", help="save only the soundtrack (mp3, wav, ...)")

    args = ap.parse_args(argv)
    rec = not args.no_recursive

    if args.cmd == "audio":
        files = audio.collect_inputs(args.inputs, recursive=rec)
        opts = audio.AudioOptions(args.bitrate, args.sample_rate, args.channels,
                                  copy_metadata=not args.no_metadata, overwrite=args.overwrite)
        run = lambda cb: audio.convert_batch(files, args.format, args.output_dir, opts,
                                             workers=args.jobs, on_file_done=cb)
    elif args.cmd == "image":
        files = image.collect_inputs(args.inputs, recursive=rec)
        opts = image.ImageOptions(quality=args.quality, max_width=args.max_width,
                                  max_height=args.max_height, overwrite=args.overwrite)
        run = lambda cb: image.convert_batch(files, args.format, args.output_dir, opts,
                                             workers=args.jobs, on_file_done=cb)
    else:
        files = video.collect_inputs(args.inputs, recursive=rec)
        opts = video.VideoOptions(crf=args.crf, height=args.height, fps=args.fps,
                                  overwrite=args.overwrite)
        if args.extract_audio:
            def run(cb):
                from .common import ConversionError, ConversionResult
                out = []
                for f in files:
                    try:
                        r = ConversionResult(f, video.extract_audio(
                            f, args.extract_audio, args.output_dir, overwrite=args.overwrite), True)
                    except ConversionError as e:
                        r = ConversionResult(f, None, False, str(e))
                    cb(r)
                    out.append(r)
                return out
        else:
            run = lambda cb: video.convert_batch(files, args.format, args.output_dir, opts,
                                                 workers=min(args.jobs, 2), on_file_done=cb)

    if not files:
        print("No matching files found.", file=sys.stderr)
        return 2

    def done(r):
        print(f"OK   {r.source} -> {r.target}" if r.ok else f"FAIL {r.source}: {r.error}")

    results = run(done)
    failed = sum(not r.ok for r in results)
    print(f"{len(results) - failed}/{len(results)} converted")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
