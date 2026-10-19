"""Entry point for the packaged Windows app (PyInstaller needs a top-level script, not a package __main__)."""

import sys

from dataconverter.gui.app import main

if __name__ == "__main__":
    sys.exit(main())
