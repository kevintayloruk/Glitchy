# Third-Party Notices

Glitchy is built with the following open source components. This is a
good-faith summary for attribution purposes, not a legal opinion -- see
each project's own repository for the authoritative license text.

## Qt / PySide6
Copyright (C) The Qt Company Ltd.
License: GNU Lesser General Public License v3 (LGPLv3)
PySide6 provides the GUI toolkit Glitchy is built on. Qt is dynamically
linked, not modified, and its full source is available from
https://code.qt.io -- satisfying LGPLv3's core distribution terms.
https://www.qt.io/licensing/

## NumPy
Copyright (c) 2005-2024, NumPy Developers.
License: BSD 3-Clause
https://numpy.org

## SciPy
Copyright (c) 2001-2024 SciPy Developers.
License: BSD 3-Clause
https://scipy.org

## soundfile
Copyright (c) 2013, Bastian Bechtold.
License: BSD 3-Clause
https://github.com/bastibe/python-soundfile

## libsndfile
Copyright (C) 1999-2016 Erik de Castro Lopo.
License: GNU Lesser General Public License v2.1 (LGPLv2.1)
Used by soundfile for reading/writing audio files. Dynamically linked;
source available from https://github.com/libsndfile/libsndfile.

## sounddevice
Copyright (c) 2015-2024 Matthias Geier.
License: MIT
https://github.com/spatialaudio/python-sounddevice

## PortAudio
Copyright (c) 1999-2011 Ross Bencina and Phil Burk.
License: MIT
Used by sounddevice for audio device I/O. http://www.portaudio.com

## FFmpeg
Copyright (c) the FFmpeg developers.
License: GNU General Public License v3 or later (GPL-3.0-or-later).
Homebrew's `ffmpeg` formula builds with `--enable-gpl` by default (pulling
in libx264/libx265 among others), which puts the resulting binary under
GPL rather than LGPL. The macOS build bundles this binary (via
`build_mac.sh`, using `dylibbundler` to relocate its dependencies) so
Network Stream mode works without a separate ffmpeg install. It is invoked
as a completely separate subprocess -- never linked into Glitchy's own
code -- which is the standard "mere aggregation" case under GPL: it does
not require Glitchy's own code to be GPL-licensed. Redistributing the
bundled binary does mean its corresponding source must remain available,
which ffmpeg.org's public source (https://ffmpeg.org) satisfies. If
ffmpeg isn't found bundled, Glitchy falls back to whatever ffmpeg build
you already have installed, and you're responsible for that build's own
terms.

## PyInstaller
Copyright (c) 2010-2024, PyInstaller Development Team.
License: GNU General Public License v2 (GPLv2) with a bundling exception
that explicitly permits distributing the applications it packages
(including Glitchy) under any license.
https://pyinstaller.org
