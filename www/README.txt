PROJECT AUSSIE

How to play on a computer
-------------------------
The game loads its car models and sounds with fetch(), and browsers block
that for files opened straight from disk (double-clicking index.html).
Run a small local web server from this folder instead:

  1. Open a terminal in this folder (the one with index.html in it).
  2. Run:   python3 -m http.server 8000
     (on Windows you may need:  py -m http.server 8000)
  3. Open http://localhost:8000 in Chrome, Edge or Firefox.

Any static web host works too (GitHub Pages, Netlify, itch.io as an HTML game):
upload the whole folder with index.html at the top level.

Missing file
------------
assets/barra.wav (the main Barra engine sound, ~4.4 MB) could not be exported:
it is over the size limit for downloading files out of the artifact.
Without it the Barra engine sound will not load. Other engines are unaffected.
If you have a copy of barra.wav, put it in the assets folder.
