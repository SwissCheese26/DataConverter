# Dateitypen-Checkliste

Abarbeitungsliste der gängigen Dateitypen. `[x]` = Backend vorhanden.
(Die gleiche Liste liegt als Doc: https://claude.ai/code/artifact/e4b1dd39-7e92-4345-89e5-c3eadff2c41c)

## Audio (ffmpeg)
- [x] MP3
- [x] WAV
- [x] FLAC
- [x] OGG (Vorbis)
- [x] Opus
- [x] AAC
- [x] M4A
- [x] WMA
- [x] AIFF
- [ ] MIDI (nur Rendern zu WAV/MP3, braucht Soundfont)
- [ ] AMR, AC3, MKA (nur als Eingabe, Ausgabe optional)

## Bilder (Pillow / ImageMagick)
- [ ] JPG / JPEG
- [ ] PNG
- [ ] WEBP
- [ ] GIF (auch animiert)
- [ ] BMP
- [ ] TIFF
- [ ] ICO
- [ ] HEIC / HEIF
- [ ] AVIF
- [ ] SVG (Rastern nach PNG/PDF)
- [ ] RAW (CR2, NEF, ARW, DNG)
- [ ] PSD (nur lesen)
- [ ] TGA, PPM/PGM, JPEG 2000

## Video (ffmpeg)
- [ ] MP4
- [ ] MKV
- [ ] AVI
- [ ] MOV
- [ ] WEBM
- [ ] WMV
- [ ] FLV
- [ ] MPEG / MPG
- [ ] 3GP
- [ ] M4V, TS / M2TS
- [ ] Video zu GIF
- [ ] Audio aus Video extrahieren (MP4 -> MP3)

## Dokumente
- [ ] PDF (zusammenführen, teilen, zu Bild/Text)
- [ ] DOCX / DOC
- [ ] ODT
- [ ] RTF
- [ ] TXT
- [ ] HTML
- [ ] Markdown (MD)
- [ ] EPUB, MOBI, AZW3 (E-Books)
- [ ] TeX / LaTeX

## Tabellen und Präsentationen
- [ ] XLSX / XLS
- [ ] ODS
- [ ] CSV / TSV
- [ ] PPTX / PPT
- [ ] ODP

## Daten und Konfiguration
- [ ] JSON
- [ ] XML
- [ ] YAML
- [ ] TOML
- [ ] INI
- [ ] SQL / SQLite (Export nach CSV/JSON)
- [ ] Parquet
- [ ] Base64 / Hex (Kodierung)

## Archive
- [ ] ZIP
- [ ] 7Z
- [ ] RAR (nur entpacken)
- [ ] TAR, TAR.GZ, TGZ, TAR.BZ2
- [ ] GZ, BZ2, XZ
- [ ] ISO (nur lesen)

## Sonstiges
- [ ] Untertitel: SRT, VTT, ASS, SUB
- [ ] Schriften: TTF, OTF, WOFF, WOFF2
- [ ] 3D: STL, OBJ, FBX, GLTF / GLB, 3MF
- [ ] CAD/Vektor: DXF, DWG (nur lesen)
- [ ] Zertifikate/Schlüssel: PEM, DER, PFX
- [ ] Kalender/Kontakte: ICS, VCF
- [ ] Lesezeichen: HTML, JSON
