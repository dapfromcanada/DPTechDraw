"""Crop and enlarge part of a rendered PNG: zoom_png.py in out x y w h scale"""
import sys

from PySide6.QtCore import Qt
from PySide6.QtGui import QImage

src, dst, x, y, w, h, k = sys.argv[1], sys.argv[2], *map(int, sys.argv[3:8])
img = QImage(src).copy(x, y, w, h)
img.scaled(w * k, h * k, Qt.KeepAspectRatio, Qt.FastTransformation).save(dst)
print("saved", dst)
