"""Command line front-end: `dataconverter audio <files/folders> -f mp3`."""

from __future__ import annotations

import argparse
import sys

from .audio import AudioOptions, FORMATS, collect_inputs, convert_batch


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="dataconverter")
    sub = ap.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("audio", help="convert audio files")
    a.add_argument("inputs", nargs="+", help="files or folders")
    a.add_argument("-f", "--format", required=True, choices=sorted(FORMATS))
    a.add_argument("-o", "--output-dir")
    a.add_argument("-b", "--bitrate", help="e.g. 192k")
    a.add_argument("-r", "--sample-rate", type=int)
    a.add_argument("-c", "--channels", type=int, choices=(1, 2))
    a.add_argument("--no-metadata", action="store_true")
    a.add_argument("--overwrite", action="store_true")
    a.add_argument("--no-recursive", action="store_true")
    a.add_argument("-j", "--jobs", type=int, default=2)
    args = ap.parse_args(argv)

    files = collect_inputs(args.inputs, recursive=not args.no_recursive)
    if not files:
        print("No audio files found.", file=sys.stderr)
        return 2
    opts = AudioOptions(args.bitrate, args.sample_rate, args.channels,
                        copy_metadata=not args.no_metadata, overwrite=args.overwrite)

    def done(r):
        print(f"OK   {r.source} -> {r.target}" if r.ok else f"FAIL {r.source}: {r.error}")

    results = convert_batch(files, args.format, args.output_dir, opts,
                            workers=args.jobs, on_file_done=done)
    failed = sum(not r.ok for r in results)
    print(f"{len(results) - failed}/{len(results)} converted")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
