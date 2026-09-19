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
License: GNU Lesser/General Public License (LGPL or GPL, depending on
build configuration).
Glitchy's Network Stream (SDP) mode invokes the ffmpeg binary already
installed on your system as a separate subprocess -- it is not bundled,
modified, or linked into Glitchy. You are responsible for the terms of
whatever ffmpeg build you have installed. https://ffmpeg.org

## PyInstaller
Copyright (c) 2010-2024, PyInstaller Development Team.
License: GNU General Public License v2 (GPLv2) with a bundling exception
that explicitly permits distributing the applications it packages
(including Glitchy) under any license.
https://pyinstaller.org
