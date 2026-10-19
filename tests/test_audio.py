import subprocess

import pytest

from dataconverter.audio import (
    AudioOptions, CancelToken, ConversionError,
    collect_inputs, convert, convert_batch, probe,
)
from dataconverter.audio.ffmpeg import find_tool
from dataconverter.cli import main


@pytest.fixture
def sine(tmp_path):
    p = tmp_path / "tone.wav"
    subprocess.run([find_tool("ffmpeg"), "-v", "error", "-f", "lavfi", "-i",
                    "sine=frequency=440:duration=2", "-ar", "44100", str(p)], check=True)
    return p


@pytest.mark.parametrize("fmt", ["mp3", "flac", "ogg", "opus", "m4a", "aac", "aiff"])
def test_convert_formats(sine, tmp_path, fmt):
    out = convert(sine, fmt, tmp_path / "out")
    assert out.suffix == "." + fmt and out.stat().st_size > 0
    assert 1.8 < float(probe(out)["format"]["duration"]) < 2.3


def test_options(sine, tmp_path):
    out = convert(sine, "mp3", tmp_path, AudioOptions(bitrate="96k", sample_rate=22050, channels=1))
    s = probe(out)["streams"][0]
    assert s["sample_rate"] == "22050" and s["channels"] == 1


def test_progress(sine, tmp_path):
    seen = []
    convert(sine, "flac", tmp_path, progress=seen.append)
    assert seen and seen[-1] == 1.0


def test_no_overwrite_and_same_file(sine, tmp_path):
    convert(sine, "mp3", tmp_path)
    with pytest.raises(ConversionError):
        convert(sine, "mp3", tmp_path)
    convert(sine, "mp3", tmp_path, AudioOptions(overwrite=True))
    with pytest.raises(ConversionError):
        convert(sine, "wav")


def test_bad_input_leaves_no_files(tmp_path):
    bad = tmp_path / "bad.mp3"
    bad.write_bytes(b"not audio")
    with pytest.raises(ConversionError):
        convert(bad, "wav", tmp_path / "o")
    assert not list((tmp_path / "o").iterdir())


def test_cancel(sine, tmp_path):
    c = CancelToken()
    c.cancel()
    res = convert_batch([sine], "mp3", tmp_path, cancel=c)
    assert not res[0].ok


def test_batch_and_cli(sine, tmp_path):
    (tmp_path / "bad.mp3").write_bytes(b"x")
    files = collect_inputs([tmp_path])
    assert len(files) == 2
    res = convert_batch(files, "ogg", tmp_path / "o")
    assert sorted(r.ok for r in res) == [False, True]
    assert main(["audio", str(sine), "-f", "flac", "-o", str(tmp_path / "c")]) == 0
