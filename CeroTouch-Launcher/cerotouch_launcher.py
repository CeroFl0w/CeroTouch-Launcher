"""CeroTouch Launcher - interfaz (PyQt6)
Instalar:  pip install PyQt6
Ejecutar:  python cerotouch_launcher.py
Requiere launcher_core.py en la misma carpeta.

Dos ventanas independientes (negra = jugar, blanca = skin / mods / Modrinth). Arrástralas
donde quieras; si las acercas se pegan solas y el yin-yang del fondo vuelve a formar un círculo.
El personaje de la ventana blanca es 3D: arrastra para girarlo 360°.
"""
import json
import math
import os
import random
import re
import shutil
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from PyQt6.QtCore import (QBuffer, QByteArray, QEasingCurve, QEvent, QIODevice, QObject, QPoint, QPointF, QPropertyAnimation, QRectF,
                          QSize, Qt, QTimer, pyqtSignal)
from PyQt6.QtGui import (QBrush, QColor, QFont, QIcon, QImage, QLinearGradient, QPainter,
                         QPainterPath, QPen, QPixmap, QPolygonF, QRadialGradient, QTransform)
from PyQt6.QtWidgets import (QApplication, QButtonGroup, QCheckBox, QComboBox,
                             QFileDialog, QFrame, QGraphicsDropShadowEffect,
                             QHBoxLayout, QLabel, QLineEdit, QListWidget,
                             QListWidgetItem, QMenu, QProgressBar, QPushButton,
                             QStackedWidget, QVBoxLayout, QWidget)

import launcher_core as core

BASE = Path(__file__).resolve().parent
MODS_LIBRARY = BASE / "mods_library"
CATEGORIAS = ["rendimiento", "decoracion", "otros"]
CONFIG = core.ROOT / "config.json"
VERSION_POR_DEFECTO = "1.21.11"
FALLBACK_VERSIONS = ["1.21.11", "1.21.10", "1.21.8", "1.21.4", "1.21.1",
                     "1.20.6", "1.20.4", "1.20.1", "1.19.4", "1.18.2", "1.16.5", "1.12.2", "1.8.9"]
USER_RE = re.compile(r"[A-Za-z0-9_]{3,16}")
FONDOS_SKIN = ["Limpio", "Atardecer", "Cuadrícula", "Noche"]
NOMBRES_FONDO = FONDOS_SKIN + ["Mi imagen"]       # el índice 4 es la imagen personalizada
FONDO_IMG = core.ROOT / "skin_bg.png"             # copia de tu imagen de fondo
FONDO_IMG_MAX = 1600                              # lado máximo al guardarla (para que pese poco)
ANIMAR_FONDO = True   # pon False si tu PC va justo
M = 18                # margen de cada ventana (aquí se dibuja la sombra)
ANCHO, ALTO = 500, 720
ANCHO_M = 650          # la ventana blanca es más ancha (panel + categorías)

# partículas flotantes del fondo: (x, y, velocidad, tamaño, fase)
_rng = random.Random(11)
PARTICULAS = [(_rng.random(), _rng.random(), 0.012 + _rng.random() * 0.022,
               1.2 + _rng.random() * 2.6, _rng.random() * 6.283) for _ in range(18)]


def fmt_num(n):
    try:
        n = int(n)
    except (TypeError, ValueError):
        return "0"
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f}M"
    if n >= 1_000:
        return f"{n / 1_000:.1f}k"
    return str(n)


# ============================================================ iconos propios (vectoriales)
def paint_icon(p: QPainter, name: str, c: QColor):
    """Iconos dibujados a mano en una cuadrícula de 24x24."""
    pen = QPen(c, 1.9)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    p.setPen(pen)
    p.setBrush(Qt.BrushStyle.NoBrush)
    P = QPointF

    def poly(*pts, fill=False, close=True):
        path = QPainterPath(P(*pts[0]))
        for q in pts[1:]:
            path.lineTo(P(*q))
        if close:
            path.closeSubpath()
        if fill:
            p.setBrush(c)
        p.drawPath(path)
        p.setBrush(Qt.BrushStyle.NoBrush)

    if name == "bolt":
        poly((13, 2), (5, 13.5), (11, 13.5), (10, 22), (19, 10), (13, 10), fill=True)
    elif name == "sparkle":
        poly((11, 2), (13.2, 9.8), (21, 12), (13.2, 14.2), (11, 22), (8.8, 14.2), (1, 12), (8.8, 9.8), fill=True)
        poly((19.5, 2.5), (20.4, 5), (23, 6), (20.4, 7), (19.5, 9.5), (18.6, 7), (16, 6), (18.6, 5), fill=True)
    elif name == "cube":
        poly((12, 2), (21, 7), (21, 17), (12, 22), (3, 17), (3, 7))
        p.drawLine(P(3, 7), P(12, 12)); p.drawLine(P(21, 7), P(12, 12)); p.drawLine(P(12, 12), P(12, 22))
    elif name == "layers":
        poly((12, 3), (21, 8), (12, 13), (3, 8))
        p.drawPolyline(QPolygonF([P(3, 12.5), P(12, 17.5), P(21, 12.5)]))
        p.drawPolyline(QPolygonF([P(3, 17), P(12, 22), P(21, 17)]))
    elif name == "grid":
        for x, y in ((3.5, 3.5), (13.5, 3.5), (3.5, 13.5), (13.5, 13.5)):
            p.drawRoundedRect(QRectF(x, y, 7, 7), 2, 2)
    elif name == "search":
        p.drawEllipse(P(10.5, 10.5), 6.5, 6.5); p.drawLine(P(15.5, 15.5), P(21, 21))
    elif name == "plus":
        p.drawLine(P(12, 5), P(12, 19)); p.drawLine(P(5, 12), P(19, 12))
    elif name == "folder":
        path = QPainterPath(P(3, 6)); path.lineTo(9, 6); path.lineTo(11.5, 9)
        path.lineTo(21, 9); path.lineTo(21, 19); path.lineTo(3, 19); path.closeSubpath()
        p.drawPath(path)
    elif name == "min":
        p.drawLine(P(6, 12), P(18, 12))
    elif name == "close":
        p.drawLine(P(6, 6), P(18, 18)); p.drawLine(P(18, 6), P(6, 18))
    elif name == "play":
        poly((7, 4), (20, 12), (7, 20), fill=True)
    elif name == "pause":
        p.setBrush(c)
        p.drawRoundedRect(QRectF(6, 5, 4, 14), 1.5, 1.5)
        p.drawRoundedRect(QRectF(14, 5, 4, 14), 1.5, 1.5)
        p.setBrush(Qt.BrushStyle.NoBrush)
    elif name == "user":
        p.drawEllipse(P(12, 8), 4.2, 4.2)
        path = QPainterPath(P(4, 21)); path.cubicTo(4, 14, 20, 14, 20, 21); p.drawPath(path)
    elif name == "tag":
        poly((3, 3), (12, 3), (21, 12), (12, 21), (3, 12))
        p.drawEllipse(P(8, 8), 1.4, 1.4)
    elif name == "chip":
        p.drawRoundedRect(QRectF(6, 6, 12, 12), 2.5, 2.5)
        for x in (9.5, 14.5):
            p.drawLine(P(x, 2), P(x, 6)); p.drawLine(P(x, 18), P(x, 22))
        for y in (9.5, 14.5):
            p.drawLine(P(2, y), P(6, y)); p.drawLine(P(18, y), P(22, y))
    elif name == "camera":
        p.drawRoundedRect(QRectF(3, 7, 18, 13), 3, 3); p.drawEllipse(P(12, 13.5), 3.5, 3.5)
        p.drawPolyline(QPolygonF([P(8, 7), P(9.5, 4), P(14.5, 4), P(16, 7)]))
    elif name == "uncheck":
        p.drawRoundedRect(QRectF(4, 4, 16, 16), 4, 4)
        p.drawLine(P(9, 9), P(15, 15)); p.drawLine(P(15, 9), P(9, 15))
    elif name == "link":
        p.drawEllipse(P(8.5, 12), 5.5, 5.5); p.drawEllipse(P(15.5, 12), 5.5, 5.5)
    elif name == "log":
        p.drawRoundedRect(QRectF(5, 3, 14, 18), 3, 3)
        for y in (8, 12, 16):
            p.drawLine(P(8.5, y), P(15.5, y))
    elif name == "shirt":
        poly((9, 3), (3, 7), (6, 11), (8, 9.5), (8, 21), (16, 21), (16, 9.5), (18, 11), (21, 7), (15, 3), close=False)
        path = QPainterPath(P(9, 3)); path.cubicTo(10, 6.5, 14, 6.5, 15, 3); p.drawPath(path)
    elif name == "mods":
        p.drawRoundedRect(QRectF(3.5, 9, 17, 11), 3, 3)
        p.drawLine(P(8, 9), P(8, 5)); p.drawLine(P(16, 9), P(16, 5)); p.drawLine(P(8, 5), P(16, 5))
    elif name == "desktop":
        p.drawRoundedRect(QRectF(3, 4, 18, 12.5), 2.5, 2.5)
        p.drawLine(P(12, 16.5), P(12, 20)); p.drawLine(P(8, 20.5), P(16, 20.5))
    elif name == "download":
        p.drawLine(P(12, 3), P(12, 15))
        p.drawPolyline(QPolygonF([P(6.5, 10), P(12, 15.5), P(17.5, 10)]))
        p.drawLine(P(4.5, 20), P(19.5, 20))
    elif name == "globe":
        p.drawEllipse(P(12, 12), 9, 9); p.drawEllipse(P(12, 12), 4, 9); p.drawLine(P(3, 12), P(21, 12))
    elif name == "image":
        p.drawRoundedRect(QRectF(3.5, 4.5, 17, 15), 3, 3)
        p.drawEllipse(P(9, 10), 1.8, 1.8)
        p.drawPolyline(QPolygonF([P(4.5, 17.5), P(10, 12.5), P(14, 16), P(16.5, 13.5), P(19.5, 17)]))
    elif name == "palette":
        p.drawEllipse(P(12, 12), 9, 9)
        p.setBrush(c)
        for x, y in ((8, 10), (12, 7.5), (16, 10), (15.5, 15.5)):
            p.drawEllipse(P(x, y), 1.3, 1.3)
        p.setBrush(Qt.BrushStyle.NoBrush)


def ico(name, color="#ffffff", size=18) -> QIcon:
    pm = QPixmap(size * 2, size * 2)
    pm.setDevicePixelRatio(2)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.scale(size / 24, size / 24)
    paint_icon(p, name, QColor(color))
    p.end()
    return QIcon(pm)


def pixmap_redondo(data, lado=38, radio=9):
    """Icono de un mod (bytes de imagen) con esquinas redondeadas; None si no se puede leer."""
    pm = QPixmap()
    if not pm.loadFromData(data) or pm.isNull():
        return None
    L = lado * 2
    pm = pm.scaled(L, L, Qt.AspectRatioMode.KeepAspectRatioByExpanding, Qt.TransformationMode.SmoothTransformation)
    out = QPixmap(L, L)
    out.fill(Qt.GlobalColor.transparent)
    p = QPainter(out)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    path = QPainterPath()
    path.addRoundedRect(QRectF(0, 0, L, L), radio * 2, radio * 2)
    p.setClipPath(path)
    p.drawPixmap((L - pm.width()) // 2, (L - pm.height()) // 2, pm)
    p.end()
    out.setDevicePixelRatio(2)
    return out


def draw_yinyang(p: QPainter, cx, cy, r, angle=0.0, alpha=255, ring=True):
    p.save()
    p.translate(cx, cy)
    p.rotate(angle)
    dark, light = QColor(8, 8, 8, alpha), QColor(245, 245, 245, alpha)
    rect = QRectF(-r, -r, 2 * r, 2 * r)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(light)
    p.drawEllipse(rect)
    half = QPainterPath(); half.moveTo(0, -r); half.arcTo(rect, 90, 180); half.closeSubpath()
    up = QPainterPath(); up.addEllipse(QPointF(0, -r / 2), r / 2, r / 2)
    low = QPainterPath(); low.addEllipse(QPointF(0, r / 2), r / 2, r / 2)
    p.fillPath(half.united(up).subtracted(low), dark)
    d = r / 7
    p.setBrush(light); p.drawEllipse(QPointF(0, -r / 2), d, d)
    p.setBrush(dark); p.drawEllipse(QPointF(0, r / 2), d, d)
    if ring:
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(QPen(QColor(255, 255, 255, min(alpha, 130)), max(1.0, r / 60)))
        p.drawEllipse(rect)
    p.restore()


def dibujar_destello(p: QPainter, x, y, s):
    """Estrella de 4 puntas."""
    pts = []
    for i in range(8):
        ang = i * math.pi / 4 - math.pi / 2
        rad = s if i % 2 == 0 else s * 0.3
        pts.append(QPointF(x + math.cos(ang) * rad, y + math.sin(ang) * rad))
    p.drawPolygon(QPolygonF(pts))


LADOS_ICONO = (16, 24, 32, 48, 64, 128, 256)


def logo_imagen(lado):
    """Yin-yang con fondo transparente (para el icono de la app y del acceso directo)."""
    img = QImage(lado, lado, QImage.Format.Format_ARGB32)
    img.fill(Qt.GlobalColor.transparent)
    p = QPainter(img)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    r = lado / 2 - max(1.0, lado * 0.035)
    draw_yinyang(p, lado / 2, lado / 2, r, 0, 255, ring=False)
    p.setBrush(Qt.BrushStyle.NoBrush)                       # borde gris: se ve en fondos claros y oscuros
    p.setPen(QPen(QColor(135, 135, 140, 235), max(1.0, lado / 36)))
    p.drawEllipse(QPointF(lado / 2, lado / 2), r, r)
    p.end()
    return img


def logo_icon():
    ic = QIcon()
    for lado in LADOS_ICONO:
        ic.addPixmap(QPixmap.fromImage(logo_imagen(lado)))
    return ic


def guardar_iconos(carpeta):
    """Guarda cerotouch.ico y cerotouch.png (256) en la carpeta; devuelve (ico, png)."""
    carpeta = Path(carpeta)
    carpeta.mkdir(parents=True, exist_ok=True)
    pngs = {}
    for lado in LADOS_ICONO:
        ba = QByteArray(); buf = QBuffer(ba); buf.open(QIODevice.OpenModeFlag.WriteOnly)
        logo_imagen(lado).save(buf, "PNG"); buf.close()
        pngs[lado] = bytes(ba.data())
    ico, png = carpeta / "cerotouch.ico", carpeta / "cerotouch.png"
    core.build_ico(pngs, ico)
    png.write_bytes(pngs[256])
    return ico, png


class YinYang(QWidget):
    def __init__(self, size=50):
        super().__init__()
        self.setFixedSize(size, size)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        draw_yinyang(p, self.width() / 2, self.height() / 2, self.width() / 2 - 2)


# ============================================================ widgets pequeños
class Seccion(QWidget):
    """Etiqueta de sección con icono propio y una línea que se desvanece."""
    def __init__(self, icono, texto, oscuro=True):
        super().__init__()
        lay = QHBoxLayout(self); lay.setContentsMargins(0, 0, 0, 0); lay.setSpacing(7)
        ic = QLabel()
        ic.setPixmap(ico(icono, "#a0a0a0" if oscuro else "#555555", 14).pixmap(QSize(14, 14)))
        t = QLabel(texto.upper()); t.setObjectName("secDark" if oscuro else "secLight")
        linea = QFrame(); linea.setFixedHeight(1)
        linea.setObjectName("secLineDark" if oscuro else "secLineLight")
        lay.addWidget(ic); lay.addWidget(t)
        lay.addWidget(linea, 1, Qt.AlignmentFlag.AlignVCenter)


class PuntoEstado(QWidget):
    """Puntito de color con brillo: verde = listo, ámbar = aviso, rojo = error, azul = trabajando."""
    COLORES = {"ok": (120, 230, 150), "warn": (255, 196, 90),
               "err": (255, 110, 110), "work": (160, 200, 255)}

    def __init__(self):
        super().__init__()
        self.setFixedSize(16, 16)
        self.modo, self.fase = "ok", 0.0

    def poner(self, modo):
        self.modo = modo
        self.update()

    def paintEvent(self, _):
        r, g, b = self.COLORES.get(self.modo, self.COLORES["ok"])
        pulso = 0.65 + 0.35 * math.sin(self.fase * 2.2) if self.modo == "work" else 1.0
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        c = QPointF(8, 8)
        glow = QRadialGradient(c, 8)
        glow.setColorAt(0, QColor(r, g, b, int(150 * pulso))); glow.setColorAt(1, QColor(r, g, b, 0))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(glow); p.drawEllipse(c, 8, 8)
        p.setBrush(QColor(r, g, b, int(255 * pulso))); p.drawEllipse(c, 3.6, 3.6)


def boton_icono(nombre, tip, oscuro):
    b = QPushButton()
    b.setObjectName("iconDark" if oscuro else "iconLight")
    b.setIcon(ico(nombre, "#eeeeee" if oscuro else "#151515", 16))
    b.setIconSize(QSize(16, 16)); b.setFixedSize(34, 34); b.setToolTip(tip)
    b.setCursor(Qt.CursorShape.PointingHandCursor)
    return b


def boton_texto(nombre_icono, texto, obj, color):
    b = QPushButton("  " + texto)
    b.setObjectName(obj); b.setIcon(ico(nombre_icono, color, 16)); b.setIconSize(QSize(16, 16))
    b.setCursor(Qt.CursorShape.PointingHandCursor)
    return b


class Segmentado(QWidget):
    """Botones tipo 'chip' con icono; solo uno activo."""
    cambio = pyqtSignal(str)

    def __init__(self, items, oscuro=True, vertical=False):
        super().__init__()
        self.oscuro, self.items = oscuro, items
        lay = QVBoxLayout(self) if vertical else QHBoxLayout(self); lay.setContentsMargins(0, 0, 0, 0); lay.setSpacing(8)
        self.grupo = QButtonGroup(self); self.grupo.setExclusive(True)
        self.botones = {}
        for texto, icono in items:
            b = QPushButton("  " + texto); b.setCheckable(True)
            b.setObjectName("chipDark" if oscuro else "chipLight")
            b.setCursor(Qt.CursorShape.PointingHandCursor); b.setIconSize(QSize(16, 16))
            self.grupo.addButton(b); lay.addWidget(b, 1); self.botones[texto] = b
            b.toggled.connect(lambda on, t=texto: self._toggle(t, on))
        self.set_actual(items[0][0])

    def _toggle(self, texto, on):
        for t, i in self.items:
            chk = self.botones[t].isChecked()
            col = ("#0a0a0a" if chk else "#dcdcdc") if self.oscuro else ("#ffffff" if chk else "#222222")
            self.botones[t].setIcon(ico(i, col, 16))
        if on:
            self.cambio.emit(texto)

    def actual(self):
        return next(t for t, b in self.botones.items() if b.isChecked())

    def indice(self):
        return [t for t, _ in self.items].index(self.actual())

    def set_actual(self, texto):
        if texto in self.botones:
            self.botones[texto].setChecked(True)
            self._toggle(texto, True)


# ============================================================ ventana base (flotante, con degradado y decoración)
class Ventana(QWidget):
    def __init__(self, oscuro, flags=Qt.WindowType.Window, ancho=ANCHO):
        super().__init__()
        self.oscuro = oscuro
        self.otro = None
        self.angulo = 0.0
        self.fase = 0.0          # tiempo de la animación (lo actualiza App.tick)
        self._drag = None
        self._cache, self._cache_key = None, None
        self.setObjectName("winDark" if oscuro else "winLight")
        self.setWindowFlags(flags | Qt.WindowType.FramelessWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setWindowTitle("CeroTouch Launcher")
        self.resize(ancho, ALTO)
        self.root = QVBoxLayout(self)
        self.root.setContentsMargins(M + 30, M + 22, M + 30, M + 22)
        self.root.setSpacing(7)

    def interior(self):
        return QRectF(self.rect()).adjusted(M, M, -M, -M)

    def _tinta(self, a):
        return QColor(255, 255, 255, int(a)) if self.oscuro else QColor(0, 0, 0, int(a))

    # ---- capa estática (se dibuja una vez y se guarda: así animar el fondo casi no cuesta)
    def _fondo_estatico(self):
        dpr = self.devicePixelRatioF()
        key = (self.width(), self.height(), dpr)
        if self._cache is not None and self._cache_key == key:
            return self._cache
        pm = QPixmap(max(1, int(self.width() * dpr)), max(1, int(self.height() * dpr)))
        pm.setDevicePixelRatio(dpr)
        pm.fill(Qt.GlobalColor.transparent)
        p = QPainter(pm)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = self.interior()
        # sombra suave
        p.setBrush(Qt.BrushStyle.NoBrush)
        for i in range(M):
            a = int(46 * (1 - i / M) ** 2.4)
            p.setPen(QPen(QColor(0, 0, 0, a), 1))
            p.drawRoundedRect(r.adjusted(-i, -i + 3, i, i + 3), 22 + i, 22 + i)
        path = QPainterPath(); path.addRoundedRect(r, 22, 22)

        # degradado base (fondos al ~50 % de opacidad)
        g = QLinearGradient(r.topLeft(), r.bottomRight())
        if self.oscuro:
            g.setColorAt(0.0, QColor(44, 44, 50, 175)); g.setColorAt(0.45, QColor(16, 16, 18, 165))
            g.setColorAt(1.0, QColor(0, 0, 0, 185))
        else:
            g.setColorAt(0.0, QColor(255, 255, 255, 185)); g.setColorAt(0.5, QColor(218, 218, 224, 160))
            g.setColorAt(1.0, QColor(160, 160, 168, 180))
        p.fillPath(path, g)

        p.setClipPath(path)
        # resplandor suave
        if self.oscuro:
            glow = QRadialGradient(QPointF(r.left() + 90, r.top() + 60), 340)
            glow.setColorAt(0, QColor(255, 255, 255, 55)); glow.setColorAt(1, QColor(255, 255, 255, 0))
        else:
            glow = QRadialGradient(QPointF(r.right() - 60, r.bottom() - 40), 360)
            glow.setColorAt(0, QColor(0, 0, 0, 60)); glow.setColorAt(1, QColor(0, 0, 0, 0))
        p.fillPath(path, glow)
        self._decorar(p, r)
        p.end()
        self._cache, self._cache_key = pm, key
        return pm

    def _decorar(self, p, r):
        """Detalles del fondo: brillo superior, segundo resplandor, anillos con marcas
        alrededor del yin-yang, cuadrícula de puntos que se desvanece y rayado en una esquina."""
        osc = self.oscuro
        cx = r.right() if osc else r.left()
        cy = r.center().y()

        # 1) brillo superior (efecto cristal)
        g = QLinearGradient(QPointF(r.left(), r.top()), QPointF(r.left(), r.top() + 130))
        g.setColorAt(0, QColor(255, 255, 255, 46 if osc else 130)); g.setColorAt(1, QColor(255, 255, 255, 0))
        p.fillRect(QRectF(r.left(), r.top(), r.width(), 130), QBrush(g))

        # 2) segundo resplandor en la esquina opuesta al símbolo
        if osc:
            g2 = QRadialGradient(QPointF(r.left() + 40, r.bottom() - 50), 300)
            g2.setColorAt(0, QColor(255, 255, 255, 30)); g2.setColorAt(1, QColor(255, 255, 255, 0))
        else:
            g2 = QRadialGradient(QPointF(r.right() - 30, r.top() + 40), 320)
            g2.setColorAt(0, QColor(255, 255, 255, 140)); g2.setColorAt(1, QColor(255, 255, 255, 0))
        p.fillRect(r, QBrush(g2))

        # 3) anillos y marcas alrededor del yin-yang (el símbolo mide 235 de radio)
        p.setBrush(Qt.BrushStyle.NoBrush)
        for rad, a in ((278, 26), (332, 17), (388, 12), (448, 8)):
            p.setPen(QPen(self._tinta(a), 1))
            p.drawEllipse(QPointF(cx, cy), rad, rad)
        punteado = QPen(self._tinta(40), 1.3)
        punteado.setDashPattern([1.2, 6.5]); punteado.setCapStyle(Qt.PenCapStyle.RoundCap)
        p.setPen(punteado)
        p.drawEllipse(QPointF(cx, cy), 303, 303)
        for k in range(0, 360, 6):
            ang = math.radians(k)
            grande = k % 30 == 0
            r1, r2 = 245, 245 + (13 if grande else 6)
            p.setPen(QPen(self._tinta(62 if grande else 34), 1.2))
            p.drawLine(QPointF(cx + math.cos(ang) * r1, cy + math.sin(ang) * r1),
                       QPointF(cx + math.cos(ang) * r2, cy + math.sin(ang) * r2))

        # 4) cuadrícula de puntos: más visible cerca del símbolo, se apaga con la distancia
        pen = QPen(self._tinta(40), 1.7)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        paso = 20.0
        y = r.top() + 12
        while y < r.bottom():
            x = r.left() + 12
            while x < r.right():
                d = math.hypot(x - cx, y - cy)
                if d > 252:
                    a = 44 * max(0.0, 1 - (d - 252) / 430)
                    if a >= 3:
                        pen.setColor(self._tinta(a))
                        p.setPen(pen)
                        p.drawPoint(QPointF(x, y))
                x += paso
            y += paso

        # 5) rayado diagonal en la esquina inferior opuesta al símbolo
        bx = r.left() if osc else r.right()
        s = 1 if osc else -1
        for k in range(12, 190, 10):
            p.setPen(QPen(self._tinta(26 * (1 - k / 190)), 1))
            p.drawLine(QPointF(bx, r.bottom() - k), QPointF(bx + s * k, r.bottom()))

    # ---- capa animada: partículas que suben flotando
    def _particulas(self, p, r):
        p.setPen(Qt.PenStyle.NoPen)
        for fx, fy, vel, tam, fase in PARTICULAS:
            t = (fy - self.fase * vel) % 1.0
            x = r.left() + fx * r.width() + math.sin(self.fase * 0.6 + fase) * 9
            y = r.top() + t * r.height()
            a = (0.35 + 0.65 * abs(math.sin(self.fase * 1.3 + fase))) * math.sin(math.pi * t)
            p.setBrush(self._tinta(105 * a))
            if tam > 2.6:
                dibujar_destello(p, x, y, tam * 2.3)
            else:
                p.drawEllipse(QPointF(x, y), tam, tam)

    # ---- marco: línea interior, borde con brillo y esquinas
    def _marco(self, p, r, path):
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(QPen(self._tinta(20), 1))
        p.drawRoundedRect(r.adjusted(6, 6, -6, -6), 17, 17)

        bg = QLinearGradient(r.topLeft(), r.bottomLeft())
        if self.oscuro:
            bg.setColorAt(0, QColor(255, 255, 255, 140)); bg.setColorAt(1, QColor(255, 255, 255, 12))
        else:
            bg.setColorAt(0, QColor(255, 255, 255, 230)); bg.setColorAt(1, QColor(0, 0, 0, 45))
        p.setPen(QPen(bg, 1.3))
        p.drawPath(path)

        esq = QPen(self._tinta(120 if self.oscuro else 105), 1.4)
        esq.setCapStyle(Qt.PenCapStyle.RoundCap)
        p.setPen(esq)
        i, L = 17, 12
        for sx, ex, sy, ey in ((r.left() + i, 1, r.top() + i, 1), (r.right() - i, -1, r.top() + i, 1),
                               (r.left() + i, 1, r.bottom() - i, -1), (r.right() - i, -1, r.bottom() - i, -1)):
            p.drawLine(QPointF(sx, sy), QPointF(sx + ex * L, sy))
            p.drawLine(QPointF(sx, sy), QPointF(sx, sy + ey * L))

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = self.interior()
        p.drawPixmap(0, 0, self._fondo_estatico())
        path = QPainterPath(); path.addRoundedRect(r, 22, 22)
        p.setClipPath(path)
        # mitad de yin-yang: pegadas, forman el símbolo completo
        cx = r.right() if self.oscuro else r.left()
        draw_yinyang(p, cx, r.center().y(), 235, self.angulo, alpha=60)
        self._particulas(p, r)
        p.setClipping(False)
        self._marco(p, r, path)

    # ---- mover libremente (desde cualquier parte vacía) + imán entre ventanas
    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self._drag = e.globalPosition().toPoint() - self.frameGeometry().topLeft()

    def mouseMoveEvent(self, e):
        if self._drag is not None and e.buttons() & Qt.MouseButton.LeftButton:
            self.move(self._imantar(e.globalPosition().toPoint() - self._drag))

    def mouseReleaseEvent(self, _):
        self._drag = None

    def _imantar(self, pos):
        o, T = self.otro, 28
        if o is None or not o.isVisible():
            return pos
        x, y = pos.x(), pos.y()
        if abs(y - o.y()) < ALTO // 2:  # solo si se solapan en vertical
            gx = (o.x() + M) - (x + self.width() - M)
            if abs(gx) < T:
                x += gx
            gx2 = (x + M) - (o.x() + o.width() - M)
            if abs(gx2) < T:
                x -= gx2
            if abs(y - o.y()) < T:
                y = o.y()
        pos.setX(int(x)); pos.setY(int(y))
        return pos


# ============================================================ ventana NEGRA: jugar
class VentanaJugar(Ventana):
    def __init__(self):
        super().__init__(True)
        self.on_restaurar = None
        self.aviso_activo = False
        r = self.root

        head = QHBoxLayout(); head.setSpacing(14)
        head.addWidget(YinYang(52))
        tit = QVBoxLayout(); tit.setSpacing(0)
        t = QLabel("CEROTOUCH")
        f = QFont("Segoe UI", 21, QFont.Weight.Black); f.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 4)
        t.setFont(f)
        s = QLabel("L A U N C H E R"); s.setObjectName("subDark")
        pill = QLabel(f"v{core.LAUNCHER_VERSION}"); pill.setObjectName("pill")
        fila_sub = QHBoxLayout(); fila_sub.setSpacing(8)
        fila_sub.addWidget(s); fila_sub.addWidget(pill); fila_sub.addStretch()
        tit.addWidget(t); tit.addLayout(fila_sub)
        head.addLayout(tit); head.addStretch()
        self.b_unir = boton_icono("link", "Unir ventanas", True)
        self.b_mods = boton_icono("mods", "Mostrar / ocultar skin y mods", True)
        self.b_min = boton_icono("min", "Minimizar", True)
        self.b_close = boton_icono("close", "Cerrar", True)
        for b in (self.b_unir, self.b_mods, self.b_min, self.b_close):
            head.addWidget(b)
        r.addLayout(head)
        sep = QFrame(); sep.setObjectName("sepDark"); sep.setFixedHeight(1)
        r.addSpacing(2); r.addWidget(sep); r.addSpacing(6)

        r.addWidget(Seccion("user", "Usuario"))
        self.usuario = QLineEdit(); self.usuario.setPlaceholderText("Tu nombre (3-16 letras, números o _)")
        self.usuario.setMaxLength(16)
        r.addWidget(self.usuario); r.addSpacing(4)

        r.addWidget(Seccion("layers", "Loader"))
        self.loader = Segmentado([("Vanilla", "cube"), ("Fabric", "layers"), ("Quilt", "grid")], True)
        r.addWidget(self.loader); r.addSpacing(4)

        r.addWidget(Seccion("tag", "Versión de Minecraft"))
        self.version = QComboBox(); self.version.addItem("Cargando versiones…")
        r.addWidget(self.version)
        self.snapshots = QCheckBox("  Mostrar snapshots")
        r.addWidget(self.snapshots); r.addSpacing(4)

        r.addWidget(Seccion("chip", "Memoria RAM"))
        self.ram = QComboBox()
        total = core.total_ram_gb()
        opciones = [2, 3, 4, 6, 8, 12, 16]
        if total:  # solo ofrecemos lo que tu equipo puede dar (dejando 1 GB al sistema)
            opciones = [o for o in opciones if o <= total - 1] or [2]
        self.ram.addItems([f"{o} GB" for o in opciones])
        self.ram.setCurrentText("4 GB")
        r.addWidget(self.ram)

        r.addStretch()
        self.banner = QFrame(); self.banner.setObjectName("card")
        bl = QHBoxLayout(self.banner); bl.setContentsMargins(14, 9, 9, 9); bl.setSpacing(8)
        bic = QLabel(); bic.setPixmap(ico("desktop", "#d8d8d8", 18).pixmap(QSize(18, 18)))
        btxt = QLabel("¿Crear un acceso directo en el escritorio?"); btxt.setObjectName("resumen")
        btxt.setWordWrap(True)
        self.b_atajo_si = QPushButton("Crear"); self.b_atajo_si.setObjectName("solidDark")
        self.b_atajo_no = QPushButton("Ahora no"); self.b_atajo_no.setObjectName("ghostDark")
        for b in (self.b_atajo_si, self.b_atajo_no):
            b.setCursor(Qt.CursorShape.PointingHandCursor)
        bl.addWidget(bic); bl.addWidget(btxt, 1); bl.addWidget(self.b_atajo_si); bl.addWidget(self.b_atajo_no)
        self.banner.hide()
        card = QFrame(); card.setObjectName("card")
        cl = QHBoxLayout(card); cl.setContentsMargins(14, 10, 14, 10)
        ic = QLabel(); ic.setPixmap(ico("sparkle", "#d8d8d8", 16).pixmap(QSize(16, 16)))
        self.resumen = QLabel("—"); self.resumen.setObjectName("resumen")
        cl.addWidget(ic); cl.addWidget(self.resumen, 1)
        self.card_resumen = card
        r.addWidget(card); r.addWidget(self.banner); r.addSpacing(4)

        fila = QHBoxLayout(); fila.setSpacing(8)
        self.punto = PuntoEstado()
        self.estado = QLabel("Listo para jugar"); self.estado.setObjectName("status")
        self.estado.setWordWrap(True); self.estado.setMinimumHeight(34)
        self.estado.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignBottom)
        self.pct = QLabel(""); self.pct.setObjectName("status")
        fila.addWidget(self.punto, 0, Qt.AlignmentFlag.AlignBottom)
        fila.addWidget(self.estado, 1); fila.addWidget(self.pct)
        r.addLayout(fila)
        self.barra = QProgressBar(); self.barra.setTextVisible(False)
        r.addWidget(self.barra); r.addSpacing(4)

        self.btn = QPushButton("  J U G A R"); self.btn.setObjectName("playBtn")
        self.btn.setIcon(ico("play", "#0a0a0a", 20)); self.btn.setIconSize(QSize(20, 20))
        self.btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.glow = QGraphicsDropShadowEffect(self)
        self.glow.setBlurRadius(36); self.glow.setOffset(0, 0); self.glow.setColor(QColor(255, 255, 255, 150))
        self.btn.setGraphicsEffect(self.glow)
        r.addWidget(self.btn); r.addSpacing(2)

        fila2 = QHBoxLayout(); fila2.setSpacing(8)
        self.btn_carpeta = boton_texto("folder", "Carpeta del juego", "ghostDark", "#dcdcdc")
        self.btn_log = boton_texto("log", "Registro", "ghostDark", "#dcdcdc")
        self.btn_atajo = boton_icono("desktop", "Crear acceso directo (escritorio y menú Inicio)", True)
        self.btn_atajo.setFixedSize(46, 40)
        fila2.addWidget(self.btn_carpeta, 1); fila2.addWidget(self.btn_log, 1); fila2.addWidget(self.btn_atajo)
        r.addLayout(fila2)

        self.pie = QLabel(""); self.pie.setObjectName("footer")
        self.pie.setAlignment(Qt.AlignmentFlag.AlignCenter)
        r.addWidget(self.pie)

    def mostrar_banner(self, ver):
        self.banner.setVisible(ver)
        self.card_resumen.setVisible(not ver)

    def aviso(self, texto, modo="ok", validacion=False):
        """Mensaje de estado con su puntito de color."""
        self.estado.setText(texto)
        self.punto.poner(modo)
        self.aviso_activo = validacion

    def poner_versiones(self, ids, preferida):
        self.version.blockSignals(True)
        self.version.clear(); self.version.addItems(ids)
        i = self.version.findText(preferida)
        self.version.setCurrentIndex(i if i >= 0 else 0)
        self.version.blockSignals(False)
        self.version.currentTextChanged.emit(self.version.currentText())

    def changeEvent(self, e):
        super().changeEvent(e)
        if e.type() == QEvent.Type.WindowStateChange and not self.isMinimized() and self.on_restaurar:
            self.on_restaurar()


# ============================================================ visor de skin 3D
class SkinView(QWidget):
    """Personaje 3D con tu skin. Arrastra para girar 360°, rueda = zoom, doble clic = reiniciar."""
    def __init__(self):
        super().__init__()
        self.img, self.slim = None, False
        self.placeholder = self._crear_placeholder()
        self.t = 0.0
        self.yaw, self.pitch, self.zoom = 25.0, -12.0, 1.0
        self.vel = 0.0
        self.animar, self.amp = True, 1.0      # balanceo de brazos y piernas (amp suaviza el cambio)
        self.fondo = 0
        self.bg_img, self._bg_pm, self._bg_key = None, None, None   # imagen de fondo propia
        self._aviso_hasta, self._aviso_txt = 0.0, ""
        self.arrastrando = False
        self._last = None
        self._ultimo_uso = 0.0
        r = random.Random(5)
        self._estrellas = [(r.random(), r.random() * 0.7, 0.6 + r.random() * 1.4, r.random() * 6.28)
                           for _ in range(34)]
        self.setMinimumHeight(250)
        self.setCursor(Qt.CursorShape.OpenHandCursor)
        self.setToolTip("Arrastra para girar 360° · Rueda: zoom · Doble clic: reiniciar")
        self.timer = QTimer(self); self.timer.timeout.connect(self._tick)

    # ---------- skin
    def set_skin(self, path, slim=False):
        self.img = QImage(str(path)).convertToFormat(QImage.Format.Format_ARGB32) if path else None
        self.slim = slim
        self.update()

    @staticmethod
    def _crear_placeholder():
        im = QImage(64, 64, QImage.Format.Format_ARGB32)
        im.fill(Qt.GlobalColor.transparent)
        p = QPainter(im)
        piel, torso, piernas = QColor(214, 160, 120), QColor(0, 160, 170), QColor(70, 70, 160)
        for rect, col in (((0, 0, 32, 16), piel), ((16, 16, 24, 16), torso),
                          ((40, 16, 16, 16), piel), ((32, 48, 16, 16), piel),
                          ((0, 16, 16, 16), piernas), ((16, 48, 16, 16), piernas)):
            p.fillRect(*rect, col)
        p.fillRect(10, 12, 2, 1, QColor(40, 40, 40)); p.fillRect(14, 12, 2, 1, QColor(40, 40, 40))  # ojos
        p.end()
        return im

    # ---------- controles públicos (los usan los botones de la ventana)
    def alternar_animacion(self):
        self.animar = not self.animar
        return self.animar

    def _fondos_disponibles(self):
        return [0, 1, 2, 3] + ([4] if self.bg_img is not None else [])

    def siguiente_fondo(self):
        lista = self._fondos_disponibles()
        i = lista.index(self.fondo) if self.fondo in lista else -1
        self.fondo = lista[(i + 1) % len(lista)]
        self._aviso_txt, self._aviso_hasta = NOMBRES_FONDO[self.fondo], time.time() + 1.4
        return NOMBRES_FONDO[self.fondo]

    def set_fondo(self, i):
        if i in self._fondos_disponibles():
            self.fondo = i

    def set_imagen(self, img):
        """Imagen propia como fondo (None la quita). Se ajusta al tamaño del visor."""
        self.bg_img = img if (img is not None and not img.isNull()) else None
        self._bg_pm = self._bg_key = None
        if self.bg_img is not None:
            self.fondo = 4
            self._aviso_txt, self._aviso_hasta = NOMBRES_FONDO[4], time.time() + 1.4
        elif self.fondo == 4:
            self.fondo = 0
        self.update()

    @staticmethod
    def _pintar_cover(p, img, W, H):
        """Rellena W×H con la imagen sin deformarla: escala hasta cubrir y recorta el sobrante, centrado."""
        iw, ih = img.width(), img.height()
        esc = max(W / iw, H / ih)
        sw, sh = W / esc, H / esc
        p.save()
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        p.drawImage(QRectF(0, 0, W, H), img, QRectF((iw - sw) / 2, (ih - sh) / 2, sw, sh))
        p.restore()

    def capturar(self, escala=3):
        """Imagen PNG del personaje (transparente si el fondo es «Limpio»)."""
        W, H = self.width(), self.height()
        img = QImage(W * escala, H * escala, QImage.Format.Format_ARGB32_Premultiplied)
        img.fill(Qt.GlobalColor.transparent)
        p = QPainter(img)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.scale(escala, escala)
        self._dibujar(p, W, H, captura=True)
        p.end()
        return img

    # ---------- ciclo de vida / animación
    def showEvent(self, e):
        self.timer.start(33)

    def hideEvent(self, e):
        self.timer.stop()

    def _tick(self):
        self.t += 0.07
        self.amp += ((1.0 if self.animar else 0.0) - self.amp) * 0.15
        if not self.arrastrando:
            if abs(self.vel) > 0.05:                       # inercia al soltar
                self.yaw += self.vel; self.vel *= 0.93
            elif time.time() - self._ultimo_uso > 2.5:     # giro automático en reposo
                self.vel = 0.0; self.yaw += 0.8
            self.yaw %= 360
        self.update()

    # ---------- ratón
    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self.arrastrando = True
            self._last = e.position()
            self.vel = 0.0
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
        e.accept()

    def mouseMoveEvent(self, e):
        if self.arrastrando and self._last is not None:
            pos = e.position()
            dx, dy = pos.x() - self._last.x(), pos.y() - self._last.y()
            self._last = pos
            self.yaw = (self.yaw + dx * 0.8) % 360
            self.vel = 0.6 * self.vel + 0.4 * dx * 0.8
            self.pitch = max(-45.0, min(20.0, self.pitch - dy * 0.4))
            self._ultimo_uso = time.time()
        e.accept()

    def mouseReleaseEvent(self, e):
        self.arrastrando = False
        self._ultimo_uso = time.time()
        self.setCursor(Qt.CursorShape.OpenHandCursor)
        e.accept()

    def mouseDoubleClickEvent(self, e):
        self.yaw, self.pitch, self.zoom, self.vel = 25.0, -12.0, 1.0, 0.0
        self._ultimo_uso = time.time()
        e.accept()

    def wheelEvent(self, e):
        f = 1.1 if e.angleDelta().y() > 0 else 1 / 1.1
        self.zoom = max(0.6, min(2.0, self.zoom * f))
        e.accept()

    # ---------- geometría 3D
    def _partes(self):
        aw = 3 if self.slim else 4
        # (textura base, textura capa 2, x0, y0, ancho, alto, fondo, balanceo)
        return [
            ((0, 0),   (32, 0),  -4,      0, 8,  8, 8,  0),   # cabeza
            ((16, 16), (16, 32), -4,      8, 8, 12, 4,  0),   # cuerpo
            ((40, 16), (40, 32), -4 - aw, 8, aw, 12, 4, +1),  # brazo derecho
            ((32, 48), (48, 48),  4,      8, aw, 12, 4, -1),  # brazo izquierdo
            ((0, 16),  (0, 32),  -4,     20, 4, 12, 4, -1),   # pierna derecha
            ((16, 48), (0, 48),   0,     20, 4, 12, 4, +1),   # pierna izquierda
        ]

    @staticmethod
    def _caras(x0, y0, z0, gw, gh, gd, u, v, w, h, d):
        """6 caras: (origen 3D, vector U, vector V, rect de textura). Geometría y textura por separado."""
        x1, y1, z1 = x0 + gw, y0 + gh, z0 + gd
        return [
            ((x0, y0, z0), (gw, 0, 0), (0, 0, gd), (u + d, v, w, d)),            # arriba
            ((x0, y1, z1), (gw, 0, 0), (0, 0, -gd), (u + d + w, v, w, d)),       # abajo
            ((x0, y0, z0), (0, 0, gd), (0, gh, 0), (u, v + d, d, h)),            # derecha
            ((x0, y0, z1), (gw, 0, 0), (0, gh, 0), (u + d, v + d, w, h)),        # frente
            ((x1, y0, z1), (0, 0, -gd), (0, gh, 0), (u + d + w, v + d, d, h)),   # izquierda
            ((x1, y0, z0), (-gw, 0, 0), (0, gh, 0), (u + 2 * d + w, v + d, w, h)),  # espalda
        ]

    # ---------- fondos del visor
    def _pintar_fondo(self, p, W, H, captura):
        if self.fondo == 4 and self.bg_img is None:
            self.fondo = 0
        if self.fondo == 0 and captura:
            return                                  # captura «Limpio»: PNG transparente
        path = QPainterPath()
        path.addRoundedRect(QRectF(0.5, 0.5, W - 1, H - 1), 16, 16)
        p.save()
        p.setClipPath(path)
        if self.fondo == 0:                         # Limpio: cristal suave
            g = QLinearGradient(0, 0, 0, H)
            g.setColorAt(0, QColor(255, 255, 255, 80)); g.setColorAt(1, QColor(255, 255, 255, 16))
            p.fillPath(path, g)
        elif self.fondo == 1:                       # Atardecer
            g = QLinearGradient(0, 0, 0, H)
            g.setColorAt(0, QColor(255, 176, 120)); g.setColorAt(0.55, QColor(214, 118, 150))
            g.setColorAt(1, QColor(84, 70, 138))
            p.fillPath(path, g)
            sol = QRadialGradient(QPointF(W / 2, H * 0.6), H * 0.42)
            sol.setColorAt(0, QColor(255, 244, 205, 210)); sol.setColorAt(1, QColor(255, 244, 205, 0))
            p.fillPath(path, sol)
            p.setPen(Qt.PenStyle.NoPen); p.setBrush(QColor(58, 40, 96, 215))
            p.drawPolygon(QPolygonF([QPointF(0, H), QPointF(0, H * 0.78), QPointF(W * 0.22, H * 0.66),
                                     QPointF(W * 0.4, H * 0.8), QPointF(W * 0.62, H * 0.62),
                                     QPointF(W * 0.84, H * 0.78), QPointF(W, H * 0.7), QPointF(W, H)]))
        elif self.fondo == 2:                       # Cuadrícula (suelo en perspectiva)
            g = QLinearGradient(0, 0, 0, H)
            g.setColorAt(0, QColor(24, 26, 36)); g.setColorAt(1, QColor(58, 62, 80))
            p.fillPath(path, g)
            hor = H * 0.6
            p.setPen(QPen(QColor(150, 200, 255, 70), 1))
            for i in range(-10, 11):
                p.drawLine(QPointF(W / 2, hor), QPointF(W / 2 + i * W / 6, H))
            for k in range(1, 9):
                y = hor + (H - hor) * (k / 8) ** 2
                p.drawLine(QPointF(0, y), QPointF(W, y))
            p.setPen(QPen(QColor(150, 200, 255, 120), 1.4))
            p.drawLine(QPointF(0, hor), QPointF(W, hor))
        elif self.fondo == 4:                       # Imagen propia, ajustada al visor
            if captura:
                self._pintar_cover(p, self.bg_img, W, H)
            else:
                dpr = self.devicePixelRatioF()
                key = (W, H, dpr)
                if self._bg_key != key or self._bg_pm is None:
                    pm = QPixmap(max(1, int(W * dpr)), max(1, int(H * dpr)))
                    pm.setDevicePixelRatio(dpr)
                    pm.fill(Qt.GlobalColor.transparent)
                    q = QPainter(pm)
                    self._pintar_cover(q, self.bg_img, W, H)
                    q.end()
                    self._bg_pm, self._bg_key = pm, key
                p.drawPixmap(0, 0, self._bg_pm)
        else:                                       # Noche
            g = QLinearGradient(0, 0, 0, H)
            g.setColorAt(0, QColor(8, 10, 26)); g.setColorAt(1, QColor(36, 36, 70))
            p.fillPath(path, g)
            p.setPen(Qt.PenStyle.NoPen)
            for fx, fy, tam, fase in self._estrellas:
                a = 90 + 150 * abs(math.sin(self.t * 0.6 + fase))
                p.setBrush(QColor(255, 255, 255, int(min(255, a))))
                p.drawEllipse(QPointF(fx * W, fy * H), tam, tam)
            luna = QRadialGradient(QPointF(W * 0.8, H * 0.17), 34)
            luna.setColorAt(0, QColor(240, 240, 255, 235)); luna.setColorAt(0.35, QColor(225, 225, 255, 120))
            luna.setColorAt(1, QColor(225, 225, 255, 0))
            p.setBrush(luna); p.drawEllipse(QPointF(W * 0.8, H * 0.17), 34, 34)
        p.restore()
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(QPen(QColor(255, 255, 255, 80) if self.fondo else QColor(0, 0, 0, 40), 1))
        p.drawPath(path)

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        self._dibujar(p, self.width(), self.height(), captura=False)

    def _dibujar(self, p, W, H, captura):
        self._pintar_fondo(p, W, H, captura)
        unit = max(3.0, min((W - 20) / 19, (H - 40) / 34)) * self.zoom
        cx, cy = W / 2, (H - 10) / 2

        # sombra en el suelo
        if not (captura and self.fondo == 0):
            sy_suelo = cy + 16.5 * unit
            sh = QRadialGradient(QPointF(cx, sy_suelo), unit * 8)
            sh.setColorAt(0, QColor(0, 0, 0, 95)); sh.setColorAt(1, QColor(0, 0, 0, 0))
            p.setPen(Qt.PenStyle.NoPen); p.setBrush(sh)
            p.drawEllipse(QPointF(cx, sy_suelo), unit * 8 * min(self.zoom, 1.3), unit * 1.8)

        img = self.img if self.img is not None else self.placeholder
        ya, pa = math.radians(self.yaw), math.radians(self.pitch)
        cyaw, syaw, cp, sp = math.cos(ya), math.sin(ya), math.cos(pa), math.sin(pa)
        swing = math.sin(self.t) * 0.3 * self.amp

        def proyectar(pt, pivote_y, ang):
            x, y, z = pt
            y -= 16                                   # centrar el modelo
            if ang:                                   # balanceo de brazos/piernas
                dy = y - (pivote_y - 16)
                c, s = math.cos(ang), math.sin(ang)
                y, z = (pivote_y - 16) + dy * c - z * s, dy * s + z * c
            x, z = x * cyaw + z * syaw, -x * syaw + z * cyaw      # giro (yaw)
            y, z = y * cp - z * sp, y * sp + z * cp              # inclinación (pitch)
            return x, y, z

        lista = []
        for base, capa, x0, y0, w, h, d, sg in self._partes():
            ang = swing * sg
            pivote = y0 if sg else 0
            for (u, v), e, bias in ((base, 0.0, 0.0), (capa, 0.5, 0.3)):
                caras = self._caras(x0 - e, y0 - e, -d / 2 - e, w + 2 * e, h + 2 * e, d + 2 * e,
                                    u, v, w, h, d)
                for o, uu, vv, tex in caras:
                    O = proyectar(o, pivote, ang)
                    U3 = proyectar((o[0] + uu[0], o[1] + uu[1], o[2] + uu[2]), pivote, ang)
                    V3 = proyectar((o[0] + vv[0], o[1] + vv[1], o[2] + vv[2]), pivote, ang)
                    Ux, Uy, Uz = U3[0] - O[0], U3[1] - O[1], U3[2] - O[2]
                    Vx, Vy, Vz = V3[0] - O[0], V3[1] - O[1], V3[2] - O[2]
                    if Ux * Vy - Uy * Vx <= 0:        # cara de espaldas: no se dibuja
                        continue
                    prof = O[2] + (Uz + Vz) / 2 + bias
                    lista.append((prof, O, (Ux, Uy), (Vx, Vy), tex))

        lista.sort(key=lambda c: c[0])                # de lejos a cerca
        for _prof, O, U, V, (tx, ty, tw, th) in lista:
            m11, m12 = U[0] * unit / tw, U[1] * unit / tw
            m21, m22 = V[0] * unit / th, V[1] * unit / th
            ox, oy = cx + O[0] * unit, cy + O[1] * unit
            dx = ox - tx * m11 - ty * m21
            dy = oy - tx * m12 - ty * m22
            p.save()
            p.setTransform(QTransform(m11, m12, m21, m22, dx, dy), True)
            r = QRectF(tx, ty, tw, th)
            p.drawImage(r, img, r)                    # sin suavizado: look pixelado de Minecraft
            p.restore()

        if captura:
            return
        if self.img is None:
            p.setPen(QColor(60, 60, 60) if self.fondo == 0 else QColor(235, 235, 245))
            p.drawText(QRectF(0, H - 36, W, 30), Qt.AlignmentFlag.AlignCenter, "Sin skin (se usa la de por defecto)")
        if time.time() < self._aviso_hasta:           # nombre del fondo, un instante
            fm = p.fontMetrics()
            ancho = fm.horizontalAdvance(self._aviso_txt) + 22
            caja = QRectF(10, 10, ancho, 24)
            p.setPen(Qt.PenStyle.NoPen); p.setBrush(QColor(0, 0, 0, 150))
            p.drawRoundedRect(caja, 12, 12)
            p.setPen(QColor(255, 255, 255, 235))
            p.drawText(caja, Qt.AlignmentFlag.AlignCenter, self._aviso_txt)


# ============================================================ ventana BLANCA: skin + mods + Modrinth
class VentanaMods(Ventana):
    cambio = pyqtSignal()
    skin_elegida = pyqtSignal(str)
    mr_buscar_sig = pyqtSignal(str)
    mr_instalar_sig = pyqtSignal(str, str, str)   # id del proyecto, título, categoría
    fondo_img_elegida = pyqtSignal(str)           # ruta ('' = abrir el selector)
    fondo_img_quitar = pyqtSignal()

    def __init__(self):
        super().__init__(False, Qt.WindowType.Tool, ANCHO_M)
        self.setAcceptDrops(True)
        self._ico_mod = ico("cube", "#444444", 18)
        self._ico_web = ico("globe", "#7a7a7a", 24)
        r = self.root

        # ---- barra superior: título + minimizar / cerrar (como en el boceto)
        head = QHBoxLayout()
        tit = QVBoxLayout(); tit.setSpacing(0)
        self.titulo = QLabel("SKIN")
        f = QFont("Segoe UI", 21, QFont.Weight.Black); f.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 4)
        self.titulo.setFont(f)
        self.sub = QLabel(""); self.sub.setObjectName("subLight")
        tit.addWidget(self.titulo); tit.addWidget(self.sub)
        head.addLayout(tit); head.addStretch()
        self.b_min = boton_icono("min", "Minimizar", False)
        self.b_close = boton_icono("close", "Ocultar esta ventana", False)
        head.addWidget(self.b_min); head.addWidget(self.b_close)
        r.addLayout(head)
        sep = QFrame(); sep.setObjectName("sepLight"); sep.setFixedHeight(1)
        r.addSpacing(2); r.addWidget(sep); r.addSpacing(4)

        cuerpo = QHBoxLayout(); cuerpo.setSpacing(16)
        self.paginas = QStackedWidget()
        self.paginas.addWidget(self._pagina_skin())
        self.paginas.addWidget(self._pagina_mods())
        self.paginas.addWidget(self._pagina_modrinth())
        cuerpo.addWidget(self.paginas, 1)

        # ---- columna derecha: CATEGORÍAS
        sep2 = QFrame(); sep2.setFixedWidth(1); sep2.setStyleSheet("background: rgba(0,0,0,45);")
        cuerpo.addWidget(sep2)
        lado = QVBoxLayout(); lado.setSpacing(10)
        lado.addWidget(Seccion("layers", "Categorías", False))
        self.cat = Segmentado([("Skin", "shirt"), ("Mods", "mods"), ("Modrinth", "globe")], False, vertical=True)
        for b in self.cat.botones.values():
            b.setMinimumHeight(46)
        lado.addWidget(self.cat); lado.addStretch()
        wl = QWidget(); wl.setFixedWidth(132); wl.setLayout(lado)
        cuerpo.addWidget(wl)
        r.addLayout(cuerpo, 1)
        self.cat.cambio.connect(self._cambiar_categoria)
        self._cambiar_categoria()
        self.cargar_mods([])

    # ---------- página SKIN
    def _pagina_skin(self):
        w = QWidget(); lay = QVBoxLayout(w); lay.setContentsMargins(0, 0, 0, 0); lay.setSpacing(6)
        self.nombre = QLabel("NOMBRE"); self.nombre.setAlignment(Qt.AlignmentFlag.AlignCenter)
        f = QFont("Segoe UI", 17, QFont.Weight.Black); f.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 3)
        self.nombre.setFont(f)
        linea = QFrame(); linea.setFixedSize(96, 3); linea.setStyleSheet("background:#111; border-radius:1px;")
        lay.addWidget(self.nombre); lay.addWidget(linea, 0, Qt.AlignmentFlag.AlignHCenter)
        self.skinview = SkinView()
        lay.addWidget(self.skinview, 1)
        self.chk_slim = QCheckBox("  Brazos delgados (Alex)")
        self.chk_slim.setStyleSheet("QCheckBox { color:#222; } ")
        lay.addWidget(self.chk_slim, 0, Qt.AlignmentFlag.AlignHCenter)
        fila = QHBoxLayout(); fila.setSpacing(8)
        self.btn_skin = boton_texto("plus", "Seleccionar", "solidLight", "#ffffff")
        self.btn_skin.setMinimumHeight(46)
        self.btn_anim = boton_icono("pause", "Pausar la animación del personaje", False)
        self.btn_fondo = boton_icono("palette", "Cambiar el fondo del visor", False)
        self.btn_bg = boton_icono("image", "Tu propia imagen de fondo", False)
        self.btn_foto = boton_icono("camera", "Guardar una captura (PNG)", False)
        self.btn_quitar_skin = boton_icono("close", "Quitar skin", False)
        botones = (self.btn_anim, self.btn_fondo, self.btn_bg, self.btn_foto, self.btn_quitar_skin)
        for b in botones:
            b.setFixedSize(42, 46)
        fila.addWidget(self.btn_skin, 1)
        for b in botones:
            fila.addWidget(b)
        lay.addLayout(fila)
        self.skin_msg = QLabel("Arrastra aquí un PNG de 64×64 o pulsa Seleccionar")
        self.skin_msg.setObjectName("subLight"); self.skin_msg.setWordWrap(True)
        self.skin_msg.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(self.skin_msg)
        self.btn_anim.clicked.connect(self._alternar_anim)
        self.btn_fondo.clicked.connect(self._siguiente_fondo)
        self.btn_foto.clicked.connect(self._guardar_captura)
        self.btn_bg.clicked.connect(self._menu_fondo_img)
        return w

    def _menu_fondo_img(self):
        menu = QMenu(self)
        a_elegir = menu.addAction("Elegir imagen…")
        a_quitar = menu.addAction("Quitar mi imagen")
        a_quitar.setEnabled(self.skinview.bg_img is not None)
        a = menu.exec(self.btn_bg.mapToGlobal(QPoint(0, self.btn_bg.height() + 4)))
        if a is a_elegir:
            self.fondo_img_elegida.emit("")
        elif a is a_quitar:
            self.fondo_img_quitar.emit()

    def _alternar_anim(self):
        on = self.skinview.alternar_animacion()
        self.btn_anim.setIcon(ico("pause" if on else "play", "#151515", 16))
        self.btn_anim.setToolTip("Pausar la animación del personaje" if on else "Reanudar la animación")

    def _siguiente_fondo(self):
        self.skin_msg.setText(f"Fondo: {self.skinview.siguiente_fondo()}")

    def _guardar_captura(self):
        sugerido = str(Path.home() / "cerotouch_skin.png")
        f, _ = QFileDialog.getSaveFileName(self, "Guardar captura", sugerido, "Imagen PNG (*.png)")
        if not f:
            return
        if not f.lower().endswith(".png"):
            f += ".png"
        ok = self.skinview.capturar().save(f, "PNG")
        self.skin_msg.setText("Captura guardada ✓" if ok else "No se pudo guardar la captura.")

    def set_nombre(self, texto):
        self.nombre.setText((texto or "").strip().upper() or "NOMBRE")

    # ---------- página MODS
    def _pagina_mods(self):
        w = QWidget(); lay = QVBoxLayout(w); lay.setContentsMargins(0, 0, 0, 0); lay.setSpacing(8)
        self.buscar = QLineEdit(); self.buscar.setPlaceholderText("Buscar mod…")
        self.buscar.addAction(ico("search", "#444444", 16), QLineEdit.ActionPosition.LeadingPosition)
        self.buscar.textChanged.connect(self.filtrar)
        lay.addWidget(self.buscar)
        self.seg = Segmentado([("Rendimiento", "bolt"), ("Decoración", "sparkle"), ("Otros", "cube")], False)
        lay.addWidget(self.seg)
        self.stack = QStackedWidget()
        self.listas = {}
        for cat in CATEGORIAS:
            lw = QListWidget(); lw.itemChanged.connect(self.actualizar_contador)
            lw.setIconSize(QSize(18, 18))
            self.listas[cat] = lw; self.stack.addWidget(lw)
        self.seg.cambio.connect(lambda _: self.stack.setCurrentIndex(self.seg.indice()))
        lay.addWidget(self.stack, 1)
        self.contador = QLabel("0 mods seleccionados"); self.contador.setObjectName("contador")
        lay.addWidget(self.contador)
        fila = QHBoxLayout(); fila.setSpacing(8)
        self.btn_add = boton_texto("plus", "Agregar", "solidLight", "#ffffff")
        self.btn_none = boton_texto("uncheck", "Limpiar", "ghostLight", "#151515")
        self.btn_dir = boton_texto("folder", "Carpeta", "ghostLight", "#151515")
        for b in (self.btn_add, self.btn_none, self.btn_dir):
            fila.addWidget(b, 1)
        lay.addLayout(fila)
        self.btn_add.clicked.connect(self.agregar)
        self.btn_none.clicked.connect(self.desmarcar)
        self.btn_dir.clicked.connect(lambda: core.open_folder(MODS_LIBRARY))
        return w

    # ---------- página MODRINTH
    def _pagina_modrinth(self):
        w = QWidget(); lay = QVBoxLayout(w); lay.setContentsMargins(0, 0, 0, 0); lay.setSpacing(8)
        self.mr_info = QLabel("—"); self.mr_info.setObjectName("subLight"); self.mr_info.setWordWrap(True)
        lay.addWidget(self.mr_info)

        fila = QHBoxLayout(); fila.setSpacing(8)
        self.mr_buscar = QLineEdit(); self.mr_buscar.setPlaceholderText("Buscar en Modrinth…  (Enter)")
        self.mr_buscar.addAction(ico("search", "#444444", 16), QLineEdit.ActionPosition.LeadingPosition)
        self.mr_btn_buscar = boton_icono("search", "Buscar", False); self.mr_btn_buscar.setFixedSize(44, 44)
        fila.addWidget(self.mr_buscar, 1); fila.addWidget(self.mr_btn_buscar)
        lay.addLayout(fila)

        self.mr_lista = QListWidget()
        self.mr_lista.setIconSize(QSize(38, 38))
        self.mr_lista.setUniformItemSizes(True)
        self.mr_lista.setVerticalScrollMode(QListWidget.ScrollMode.ScrollPerPixel)
        self.mr_lista.setTextElideMode(Qt.TextElideMode.ElideRight)
        lay.addWidget(self.mr_lista, 1)

        self.mr_detalle = QLabel("Elige un mod de la lista para ver sus detalles.")
        self.mr_detalle.setObjectName("detalle"); self.mr_detalle.setWordWrap(True)
        self.mr_detalle.setMinimumHeight(50)
        self.mr_detalle.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        lay.addWidget(self.mr_detalle)

        lay.addWidget(Seccion("layers", "Guardar en", False))
        self.mr_cat = Segmentado([("Rendimiento", "bolt"), ("Decoración", "sparkle"), ("Otros", "cube")], False)
        lay.addWidget(self.mr_cat)
        self.mr_btn_instalar = boton_texto("download", "Instalar y marcar", "solidLight", "#ffffff")
        self.mr_btn_instalar.setMinimumHeight(46)
        lay.addWidget(self.mr_btn_instalar)
        self.mr_barra = QProgressBar(); self.mr_barra.setTextVisible(False)
        lay.addWidget(self.mr_barra)
        self.mr_estado = QLabel(""); self.mr_estado.setObjectName("contador"); self.mr_estado.setWordWrap(True)
        lay.addWidget(self.mr_estado)

        self.mr_buscar.returnPressed.connect(self._mr_emitir_busqueda)
        self.mr_btn_buscar.clicked.connect(self._mr_emitir_busqueda)
        self.mr_lista.currentItemChanged.connect(self._mr_seleccion)
        self.mr_lista.itemDoubleClicked.connect(lambda _: self._mr_instalar())
        self.mr_btn_instalar.clicked.connect(self._mr_instalar)
        return w

    def mr_set_contexto(self, mc, loader):
        efectivo = "Fabric" if loader == "Vanilla" else loader
        extra = "  ·  Con Vanilla no se cargan mods: elige Fabric o Quilt para jugar con ellos." if loader == "Vanilla" else ""
        self.mr_info.setText(f"Mods para Minecraft {mc} · {efectivo}{extra}")

    def _mr_emitir_busqueda(self):
        self.mr_buscar_sig.emit(self.mr_buscar.text())

    def mr_estado_set(self, texto, ocupado=False, frac=0.0):
        self.mr_estado.setText(texto)
        self.mr_barra.setValue(int(frac * 100))
        self.mr_btn_instalar.setEnabled(not ocupado)
        self.mr_btn_buscar.setEnabled(not ocupado)

    def mr_poner_resultados(self, hits):
        self.mr_lista.clear()
        if not hits:
            it = QListWidgetItem("No hay mods compatibles con esta búsqueda")
            it.setFlags(Qt.ItemFlag.NoItemFlags)
            self.mr_lista.addItem(it)
            self.mr_estado_set("Sin resultados para esta versión y loader.")
            return
        for h in hits:
            desc = (h.get("description") or "").replace("\n", " ")
            it = QListWidgetItem(self._ico_web, f"{h.get('title', '?')}  ·  ↓ {fmt_num(h.get('downloads'))}\n{desc}")
            it.setData(Qt.ItemDataRole.UserRole, h.get("project_id"))
            it.setData(Qt.ItemDataRole.UserRole + 1, h.get("title", "?"))
            it.setData(Qt.ItemDataRole.UserRole + 2, h)
            it.setToolTip(f"{h.get('title', '?')} — por {h.get('author', '?')}")
            it.setSizeHint(QSize(0, 58))
            self.mr_lista.addItem(it)
        self.mr_lista.setCurrentRow(0)
        self.mr_estado_set(f"{len(hits)} mods encontrados. Doble clic para instalar.")

    def mr_poner_icono(self, fila, datos):
        it = self.mr_lista.item(fila)
        pm = pixmap_redondo(datos, 38) if it is not None else None
        if pm is not None:
            it.setIcon(QIcon(pm))

    def _mr_seleccion(self, actual, _previo):
        if actual is None or not actual.data(Qt.ItemDataRole.UserRole):
            return
        h = actual.data(Qt.ItemDataRole.UserRole + 2) or {}
        cats = ", ".join(h.get("display_categories") or h.get("categories") or [])
        self.mr_detalle.setText(f"por {h.get('author', '?')}" + (f"  ·  {cats}" if cats else "")
                                + f"\n{h.get('description', '')}")
        c = set(h.get("categories") or [])
        self.mr_cat.set_actual("Rendimiento" if "optimization" in c
                               else "Decoración" if "decoration" in c else "Otros")

    def _mr_instalar(self):
        it = self.mr_lista.currentItem()
        pid = it.data(Qt.ItemDataRole.UserRole) if it else None
        if not pid:
            return
        self.mr_instalar_sig.emit(pid, it.data(Qt.ItemDataRole.UserRole + 1), CATEGORIAS[self.mr_cat.indice()])

    # ---------- categorías
    def _cambiar_categoria(self, *_):
        i = self.cat.indice()
        self.paginas.setCurrentIndex(i)
        self.titulo.setText(["SKIN", "MODS", "MODRINTH"][i])
        self.sub.setText(["Así te verás al jugar", "Marca los que quieras usar (Fabric / Quilt)",
                          "Busca e instala mods con sus dependencias"][i])

    def cat_actual(self):
        return CATEGORIAS[self.stack.currentIndex()]

    def cargar_mods(self, marcados=None):
        marcados = set(marcados) if marcados is not None else set(self.mods_seleccionados_rel())
        for cat, lw in self.listas.items():
            lw.blockSignals(True)
            lw.clear()
            carpeta = MODS_LIBRARY / cat
            carpeta.mkdir(parents=True, exist_ok=True)
            jars = sorted(carpeta.glob("*.jar"), key=lambda p: p.name.lower())
            for jar in jars:
                it = QListWidgetItem(self._ico_mod, jar.stem)
                it.setFlags(it.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                rel = f"{cat}/{jar.name}"
                it.setCheckState(Qt.CheckState.Checked if rel in marcados else Qt.CheckState.Unchecked)
                it.setData(Qt.ItemDataRole.UserRole, str(jar))
                it.setData(Qt.ItemDataRole.UserRole + 1, rel)
                it.setData(Qt.ItemDataRole.UserRole + 2, jar.stem)
                try:
                    it.setToolTip(f"{jar.name}\n{jar.stat().st_size / 1048576:.2f} MB")
                except OSError:
                    pass
                lw.addItem(it)
            if not jars:
                it = QListWidgetItem("Arrastra tus .jar aquí, usa «Agregar» o instala desde Modrinth")
                it.setFlags(Qt.ItemFlag.NoItemFlags)
                lw.addItem(it)
            lw.blockSignals(False)
        self.filtrar(self.buscar.text())
        self.actualizar_contador()

    def _items(self):
        for lw in self.listas.values():
            for i in range(lw.count()):
                yield lw.item(i)

    def mods_seleccionados(self):
        return [Path(it.data(Qt.ItemDataRole.UserRole)) for it in self._items()
                if it.data(Qt.ItemDataRole.UserRole) and it.checkState() == Qt.CheckState.Checked]

    def mods_seleccionados_rel(self):
        return [it.data(Qt.ItemDataRole.UserRole + 1) for it in self._items()
                if it.data(Qt.ItemDataRole.UserRole) and it.checkState() == Qt.CheckState.Checked]

    def actualizar_contador(self, *_):
        n = len(self.mods_seleccionados())
        self.contador.setText(f"{n} mod{'s' if n != 1 else ''} seleccionado{'s' if n != 1 else ''}")
        self.cambio.emit()

    def filtrar(self, texto):
        texto = texto.lower().strip()
        for it in self._items():
            if it.data(Qt.ItemDataRole.UserRole):
                nombre = (it.data(Qt.ItemDataRole.UserRole + 2) or "").lower()
                it.setHidden(bool(texto) and texto not in nombre)

    def desmarcar(self):
        for it in self._items():
            if it.data(Qt.ItemDataRole.UserRole):
                it.setCheckState(Qt.CheckState.Unchecked)

    def agregar(self):
        files, _ = QFileDialog.getOpenFileNames(self, "Elige mods (.jar)", "", "Mods (*.jar)")
        self._copiar_mods(files)

    def _copiar_mods(self, files):
        ok = False
        for f in files:
            if f.lower().endswith(".jar"):
                shutil.copy2(f, MODS_LIBRARY / self.cat_actual() / Path(f).name)
                ok = True
        if ok:
            self.cargar_mods()

    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls():
            e.acceptProposedAction()

    def dropEvent(self, e):
        files = [u.toLocalFile() for u in e.mimeData().urls()]
        pngs = [f for f in files if f.lower().endswith(".png")]
        jars = [f for f in files if f.lower().endswith(".jar")]
        fotos = [f for f in files if f.lower().endswith((".jpg", ".jpeg", ".webp", ".bmp"))]
        if fotos and not pngs:
            self.cat.set_actual("Skin")
            self.fondo_img_elegida.emit(fotos[0])
        if pngs:
            self.cat.set_actual("Skin")
            self.skin_elegida.emit(pngs[0])
        elif jars:
            self.cat.set_actual("Mods")   # así ves en qué categoría se guardan
        self._copiar_mods(files)


# ============================================================ estilo
STYLE = """
* { font-family: 'Segoe UI Variable Display', 'Segoe UI', 'Inter', sans-serif; font-size: 13px; }
QToolTip { background: #111; color: #eee; border: 1px solid #444; padding: 5px; border-radius: 4px; }

#winDark QLabel { color: #f4f4f4; }
#winLight QLabel { color: #111; }
#winDark #secDark   { color: #a0a0a0; font-size: 10px; font-weight: 700; }
#winLight #secLight { color: #555;    font-size: 10px; font-weight: 700; }
#winDark #subDark   { color: #8e8e8e; font-size: 11px; }
#winLight #subLight { color: #555;    font-size: 11px; }
#winDark #status    { color: #c4c4c4; font-size: 12px; }
#winDark #resumen   { color: #e6e6e6; font-size: 12px; font-weight: 600; }
#winLight #contador { color: #333; font-size: 12px; font-weight: 600; }
#winLight #detalle  { color: #2a2a2a; font-size: 12px; }
#winDark #footer    { color: #7d7d7d; font-size: 10px; }
#winDark #pill { color: #cfcfcf; font-size: 10px; font-weight: 700; background: rgba(255,255,255,16);
                 border: 1px solid rgba(255,255,255,55); border-radius: 8px; padding: 1px 7px; }
#card { background: rgba(255,255,255,14); border: 1px solid rgba(255,255,255,40); border-radius: 14px; }

/* ---------- líneas decorativas ---------- */
#secLineDark  { border: none; background: qlineargradient(x1:0,y1:0,x2:1,y2:0, stop:0 rgba(255,255,255,70), stop:1 rgba(255,255,255,0)); }
#secLineLight { border: none; background: qlineargradient(x1:0,y1:0,x2:1,y2:0, stop:0 rgba(0,0,0,70), stop:1 rgba(0,0,0,0)); }
#sepDark  { border: none; background: qlineargradient(x1:0,y1:0,x2:1,y2:0, stop:0 rgba(255,255,255,0), stop:0.2 rgba(255,255,255,95), stop:0.8 rgba(255,255,255,95), stop:1 rgba(255,255,255,0)); }
#sepLight { border: none; background: qlineargradient(x1:0,y1:0,x2:1,y2:0, stop:0 rgba(0,0,0,0), stop:0.2 rgba(0,0,0,80), stop:0.8 rgba(0,0,0,80), stop:1 rgba(0,0,0,0)); }

/* ---------- campos ---------- */
#winDark QComboBox, #winDark QLineEdit {
    background: rgba(255,255,255,20); border: 1px solid rgba(255,255,255,55);
    border-radius: 12px; padding: 11px 14px; color: #f4f4f4; selection-background-color: #fff; selection-color: #000; }
#winDark QComboBox:hover, #winDark QLineEdit:hover, #winDark QLineEdit:focus {
    border: 1px solid rgba(255,255,255,170); background: rgba(255,255,255,32); }
#winDark QLineEdit[invalido="true"] { border: 1px solid rgba(255,120,120,210); background: rgba(255,90,90,26); }
#winDark QComboBox::drop-down { border: none; width: 32px; }
#winDark QComboBox::down-arrow { image: url(ARROW); width: 12px; height: 8px; }
QComboBox QAbstractItemView { background: #151515; color: #eee; border: 1px solid #444; border-radius: 8px;
    padding: 4px; selection-background-color: #f2f2f2; selection-color: #000; outline: none; }
#winLight QLineEdit { background: rgba(255,255,255,110); border: 1px solid rgba(0,0,0,60);
    border-radius: 12px; padding: 11px 14px; color: #111; }
#winLight QLineEdit:focus { border: 1px solid rgba(0,0,0,210); background: rgba(255,255,255,170); }

/* ---------- botones ---------- */
#playBtn { background: qlineargradient(x1:0,y1:0,x2:0,y2:1, stop:0 #ffffff, stop:1 #c4c4c4);
           color: #0a0a0a; border: 1px solid #ffffff; border-radius: 16px; padding: 17px; font-size: 17px; font-weight: 800; }
#playBtn:hover { background: qlineargradient(x1:0,y1:0,x2:0,y2:1, stop:0 #ffffff, stop:1 #e8e8e8); }
#playBtn:pressed { background: #b4b4b4; }
#playBtn:disabled { background: rgba(255,255,255,55); color: rgba(255,255,255,150); border: 1px solid rgba(255,255,255,40); }

#solidDark { background: #f4f4f4; color: #0a0a0a; border: 1px solid #ffffff; border-radius: 10px; padding: 8px 14px; font-weight: 700; }
#solidDark:hover { background: #ffffff; }
#ghostDark  { background: rgba(255,255,255,10); color: #dcdcdc; border: 1px solid rgba(255,255,255,60); border-radius: 11px; padding: 10px 12px; font-weight: 600; }
#ghostDark:hover  { background: rgba(255,255,255,32); border: 1px solid rgba(255,255,255,170); }
#ghostLight { background: rgba(0,0,0,10); color: #151515; border: 1px solid rgba(0,0,0,80); border-radius: 11px; padding: 10px 12px; font-weight: 600; }
#ghostLight:hover { background: rgba(0,0,0,30); border: 1px solid rgba(0,0,0,210); }
#solidLight { background: rgba(12,12,12,240); color: #fff; border: 1px solid #000; border-radius: 11px; padding: 10px 12px; font-weight: 700; }
#solidLight:hover { background: #000; }
#solidLight:disabled { background: rgba(0,0,0,90); color: rgba(255,255,255,170); border: 1px solid rgba(0,0,0,60); }

#iconDark  { background: rgba(255,255,255,16); border: 1px solid rgba(255,255,255,45); border-radius: 11px; }
#iconDark:hover  { background: rgba(255,255,255,55); border: 1px solid rgba(255,255,255,170); }
#iconLight { background: rgba(0,0,0,12); border: 1px solid rgba(0,0,0,45); border-radius: 11px; }
#iconLight:hover { background: rgba(0,0,0,42); border: 1px solid rgba(0,0,0,170); }

#chipDark { background: rgba(255,255,255,16); color: #dcdcdc; border: 1px solid rgba(255,255,255,50);
            border-radius: 12px; padding: 11px 6px; font-weight: 600; }
#chipDark:hover { background: rgba(255,255,255,36); border: 1px solid rgba(255,255,255,150); }
#chipDark:checked { background: #f4f4f4; color: #0a0a0a; border: 1px solid #ffffff; }
#chipLight { background: rgba(0,0,0,14); color: #222; border: 1px solid rgba(0,0,0,55);
             border-radius: 12px; padding: 11px 6px; font-weight: 600; }
#chipLight:hover { background: rgba(0,0,0,34); border: 1px solid rgba(0,0,0,150); }
#chipLight:checked { background: rgba(10,10,10,242); color: #fff; border: 1px solid #000; }

/* ---------- checkbox ---------- */
#winDark QCheckBox { color: #cfcfcf; spacing: 6px; }
#winDark QCheckBox::indicator { width: 16px; height: 16px; border-radius: 5px;
    border: 1px solid rgba(255,255,255,130); background: rgba(255,255,255,18); }
#winDark QCheckBox::indicator:checked { background: #fff; border: 1px solid #fff; }

/* ---------- listas (mods locales y Modrinth) ---------- */
QListWidget { background: rgba(255,255,255,80); border: 1px solid rgba(0,0,0,55); border-radius: 14px;
              color: #111; padding: 6px; outline: none; }
QListWidget::item { padding: 10px 8px; border-radius: 9px; }
QListWidget::item:hover { background: rgba(0,0,0,26); }
QListWidget::item:selected { background: rgba(0,0,0,40); color: #000; }
QListWidget::indicator { width: 16px; height: 16px; border-radius: 5px;
    border: 1px solid rgba(0,0,0,160); background: rgba(255,255,255,190); }
QListWidget::indicator:checked { background: #111; border: 1px solid #111; }

/* ---------- barras ---------- */
QProgressBar { background: rgba(255,255,255,28); border: none; border-radius: 4px; max-height: 8px; min-height: 8px; }
QProgressBar::chunk { background: qlineargradient(x1:0,y1:0,x2:1,y2:0, stop:0 #7a7a7a, stop:1 #ffffff); border-radius: 4px; }
#winLight QProgressBar { background: rgba(0,0,0,30); }
#winLight QProgressBar::chunk { background: qlineargradient(x1:0,y1:0,x2:1,y2:0, stop:0 #6a6a6a, stop:1 #0a0a0a); border-radius: 4px; }

QMenu { background: #151515; color: #eee; border: 1px solid #444; border-radius: 10px; padding: 6px; }
QMenu::item { padding: 8px 18px; border-radius: 7px; }
QMenu::item:selected { background: #f2f2f2; color: #000; }
QMenu::item:disabled { color: #777; }

QScrollBar:vertical { background: transparent; width: 8px; margin: 2px; }
QScrollBar::handle:vertical { background: rgba(0,0,0,110); border-radius: 4px; min-height: 30px; }
QScrollBar::handle:vertical:hover { background: rgba(0,0,0,200); }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
"""


def make_arrow_png():
    out = core.ROOT / "ui"
    out.mkdir(parents=True, exist_ok=True)
    path = out / "arrow.png"
    pm = QPixmap(12, 8); pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm); p.setRenderHint(QPainter.RenderHint.Antialiasing)
    pen = QPen(QColor(235, 235, 235), 1.8); pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    p.setPen(pen)
    p.drawLine(QPointF(1.5, 1.5), QPointF(6, 6)); p.drawLine(QPointF(6, 6), QPointF(10.5, 1.5))
    p.end(); pm.save(str(path))
    return path.as_posix()


def cabeza_pixmap(path):
    img = QImage(str(path)).convertToFormat(QImage.Format.Format_ARGB32)
    out = QPixmap(8, 8); out.fill(Qt.GlobalColor.transparent)
    p = QPainter(out)
    p.drawImage(0, 0, img.copy(8, 8, 8, 8)); p.drawImage(0, 0, img.copy(40, 8, 8, 8))
    p.end()
    return out.scaled(32, 32, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.FastTransformation)


# ============================================================ puentes de hilos
class Bridge(QObject):
    progress = pyqtSignal(int, str)
    launched = pyqtSignal()
    closed = pyqtSignal(int, str)
    failed = pyqtSignal(str)
    versions = pyqtSignal(list, bool)
    atajo = pyqtSignal(bool, str)


class ModrinthBridge(QObject):
    resultados = pyqtSignal(int, list)      # id de búsqueda, hits
    icono = pyqtSignal(int, int, bytes)     # id de búsqueda, fila, bytes
    progreso = pyqtSignal(int, str)         # 0-100, texto
    instalado = pyqtSignal(list, str)       # rutas, título
    error = pyqtSignal(str)


# ============================================================ controlador
class App(QObject):
    def __init__(self):
        super().__init__()
        self.cfg = self.leer_config()
        self.jugando = False
        self.mods_abiertos = True
        self.t = 0.0
        self.anims = []
        self.mr_id, self.mr_cargado, self.mr_instalando = 0, False, False
        self.bridge = Bridge()
        self.mrb = ModrinthBridge()

        self.jugar = VentanaJugar()
        self.mods = VentanaMods()
        self.jugar.otro, self.mods.otro = self.mods, self.jugar
        self.jugar.on_restaurar = self.restaurar

        b = self.bridge
        b.progress.connect(self.on_progreso); b.launched.connect(self.on_lanzado)
        b.closed.connect(self.on_cerrado); b.failed.connect(self.on_error)
        b.versions.connect(self.on_versiones)
        b.atajo.connect(self.on_atajo)
        mb = self.mrb
        mb.resultados.connect(self.on_mr_resultados); mb.icono.connect(self.on_mr_icono)
        mb.progreso.connect(self.on_mr_progreso); mb.instalado.connect(self.on_mr_instalado)
        mb.error.connect(self.on_mr_error)

        j = self.jugar
        j.btn.clicked.connect(self.iniciar)
        j.btn_carpeta.clicked.connect(lambda: core.open_folder(core.INSTANCES))
        j.btn_log.clicked.connect(self.abrir_registro)
        j.snapshots.toggled.connect(self.cargar_versiones)
        j.b_unir.clicked.connect(self.unir)
        j.b_mods.clicked.connect(self.alternar_mods)
        j.b_min.clicked.connect(self.minimizar)
        j.b_close.clicked.connect(self.salir)
        j.btn_atajo.clicked.connect(self.crear_atajos)
        j.b_atajo_si.clicked.connect(self.crear_atajos)
        j.b_atajo_no.clicked.connect(self.rechazar_atajo)
        m = self.mods
        m.btn_skin.clicked.connect(lambda: self.elegir_skin())
        m.btn_quitar_skin.clicked.connect(self.quitar_skin)
        m.skin_elegida.connect(self.elegir_skin)
        m.fondo_img_elegida.connect(self.elegir_fondo_img)
        m.fondo_img_quitar.connect(self.quitar_fondo_img)
        m.chk_slim.toggled.connect(self.recargar_vista)
        m.b_min.clicked.connect(self.minimizar)
        j.usuario.textChanged.connect(m.set_nombre)
        self.mods.b_close.clicked.connect(self.alternar_mods)
        for sig in (j.version.currentTextChanged, j.ram.currentTextChanged, j.loader.cambio):
            sig.connect(self.actualizar_resumen)
        self.mods.cambio.connect(self.actualizar_resumen)
        j.usuario.textChanged.connect(self.revisar_avisos)
        j.ram.currentTextChanged.connect(self.revisar_avisos)
        for sig in (j.version.currentTextChanged, j.loader.cambio):
            sig.connect(self.contexto_cambiado)
        m.cat.cambio.connect(self.on_categoria)
        m.mr_buscar_sig.connect(self.mr_buscar)
        m.mr_instalar_sig.connect(self.mr_instalar)
        self.mr_timer = QTimer(self); self.mr_timer.setSingleShot(True); self.mr_timer.setInterval(500)
        self.mr_timer.timeout.connect(lambda: self.mr_buscar(self.mods.mr_buscar.text()))

        j.usuario.setText(self.cfg.get("usuario", ""))
        j.loader.set_actual(self.cfg.get("loader", "Vanilla"))
        j.ram.setCurrentText(self.cfg.get("ram", "4 GB"))
        j.snapshots.setChecked(self.cfg.get("snapshots", False))
        self.mods.set_nombre(j.usuario.text())
        self.refrescar_skin(self.cfg.get("slim", False))
        self.cargar_fondo_img()
        self.mods.cargar_mods(self.cfg.get("mods", []))
        self.cargar_versiones()
        self.actualizar_pie()
        self.revisar_avisos()
        self.contexto_cambiado()

        j.mostrar_banner(core.OS_NAME in ("windows", "linux") and not self.cfg.get("atajo_ofrecido", False))

        if ANIMAR_FONDO:
            self.timer = QTimer(self); self.timer.timeout.connect(self.tick); self.timer.start(40)

    # ---- ventanas
    def mostrar(self):
        geo = QApplication.primaryScreen().availableGeometry()
        total = ANCHO + ANCHO_M - 2 * M
        x0 = geo.x() + max(0, (geo.width() - total) // 2)
        y0 = geo.y() + max(0, (geo.height() - ALTO) // 2)
        self.jugar.move(x0, y0)
        self.mods.move(x0 + self.jugar.width() - 2 * M, y0)
        for w, retraso in ((self.jugar, 0), (self.mods, 120)):
            w.setWindowOpacity(0.0)
            w.show()
            a = QPropertyAnimation(w, b"windowOpacity", self)
            a.setDuration(450); a.setStartValue(0.0); a.setEndValue(1.0)
            a.setEasingCurve(QEasingCurve.Type.OutCubic)
            QTimer.singleShot(retraso, a.start)
            self.anims.append(a)

    def unir(self):
        self.mods.move(self.jugar.x() + self.jugar.width() - 2 * M, self.jugar.y())
        if not self.mods.isVisible():
            self.mods_abiertos = True
            self.mods.show()

    def alternar_mods(self):
        self.mods_abiertos = not self.mods_abiertos
        self.mods.setVisible(self.mods_abiertos)

    def minimizar(self):
        self.mods.hide()
        self.jugar.showMinimized()

    def restaurar(self):
        if self.mods_abiertos:
            self.mods.show()

    def salir(self):
        self.guardar_config()
        QApplication.quit()

    def tick(self):
        self.t += 0.07
        ang = (self.jugar.angulo + 0.4) % 360
        for w in (self.jugar, self.mods):
            w.angulo = ang
            w.fase = self.t
            if w.isVisible():
                w.update()
        self.jugar.glow.setBlurRadius(34 + 12 * math.sin(self.t))
        self.jugar.punto.fase = self.t
        if self.jugar.punto.modo == "work":
            self.jugar.punto.update()

    # ---- config
    def leer_config(self):
        try:
            return json.loads(CONFIG.read_text())
        except Exception:
            return {}

    def guardar_config(self):
        j = self.jugar
        self.cfg = {"usuario": j.usuario.text(), "loader": j.loader.actual(),
                    "version": j.version.currentText(), "ram": j.ram.currentText(),
                    "snapshots": j.snapshots.isChecked(), "slim": self.mods.chk_slim.isChecked(), "mods": self.mods.mods_seleccionados_rel(),
                    "fondo": self.mods.skinview.fondo,
                    "atajo_ofrecido": self.cfg.get("atajo_ofrecido", False)}
        try:
            CONFIG.parent.mkdir(parents=True, exist_ok=True)
            CONFIG.write_text(json.dumps(self.cfg, indent=2))
        except Exception:
            pass

    def actualizar_resumen(self, *_):
        j = self.jugar
        n = len(self.mods.mods_seleccionados())
        mods = f" · {n} mod{'s' if n != 1 else ''}" if j.loader.actual() != "Vanilla" else ""
        j.resumen.setText(f"{j.version.currentText()} · {j.loader.actual()} · {j.ram.currentText()}{mods}")

    def actualizar_pie(self):
        partes = ["Modo offline"]
        total, libre = core.total_ram_gb(), core.free_disk_gb()
        if total:
            partes.append(f"{total:.0f} GB de RAM")
        if libre is not None:
            partes.append(f"{libre:.0f} GB libres")
        self.jugar.pie.setText("  ·  ".join(partes))

    # ---- validación en vivo (usuario y RAM)
    def revisar_avisos(self, *_):
        j = self.jugar
        t = j.usuario.text().strip()
        valido = bool(USER_RE.fullmatch(t))
        j.usuario.setProperty("invalido", bool(t) and not valido)
        j.usuario.style().unpolish(j.usuario); j.usuario.style().polish(j.usuario)
        if self.jugando:
            return
        try:
            gb = int(j.ram.currentText().split()[0])
        except (ValueError, IndexError):
            gb = 4
        nivel, msg = core.ram_check(gb)
        j.btn.setEnabled(valido and nivel != "error")
        if not t:
            j.aviso("Escribe un nombre de usuario para poder jugar", "warn", True)
        elif not valido:
            j.aviso("El usuario debe tener 3-16 caracteres: letras, números o _", "warn", True)
        elif nivel:
            j.aviso(msg, "warn" if nivel == "warn" else "err", True)
        elif j.aviso_activo:
            j.aviso("Listo para jugar", "ok")

    # ---- skin offline
    def recargar_vista(self, *_):
        m = self.mods
        m.skinview.set_skin(core.SKIN_FILE if core.SKIN_FILE.exists() else None, m.chk_slim.isChecked())

    def refrescar_skin(self, slim=None):
        m = self.mods
        hay = core.SKIN_FILE.exists()
        m.btn_quitar_skin.setVisible(hay); m.chk_slim.setVisible(hay)
        if hay and slim is not None:
            m.chk_slim.blockSignals(True); m.chk_slim.setChecked(bool(slim)); m.chk_slim.blockSignals(False)
        m.btn_skin.setText("  Cambiar skin" if hay else "  Seleccionar skin")
        self.recargar_vista()

    def elegir_skin(self, f=None):
        m = self.mods
        if not f:
            f, _ = QFileDialog.getOpenFileName(m, "Elige tu skin (PNG 64x64)", "", "Skin (*.png)")
        if not f:
            return
        img = QImage(f)
        if img.isNull() or img.width() != 64 or img.height() != 64:
            m.skin_msg.setText("La skin debe ser un PNG de 64×64 (las antiguas de 64×32 no sirven).")
            return
        core.ROOT.mkdir(parents=True, exist_ok=True)
        shutil.copy2(f, core.SKIN_FILE)
        # brazos delgados: la parte trasera del brazo (x 54-55) queda vacía
        slim = all(img.pixelColor(x, y).alpha() == 0 for x in (54, 55) for y in range(20, 32))
        self.refrescar_skin(slim)
        self.guardar_config()
        m.skin_msg.setText("Listo: se aplicará al iniciar" + (" · brazos delgados detectados" if slim else ""))

    def quitar_skin(self):
        core.SKIN_FILE.unlink(missing_ok=True)
        self.refrescar_skin()
        self.mods.skin_msg.setText("Skin quitada: se usará la de por defecto")

    # ---- fondo propio del visor de skin
    def cargar_fondo_img(self):
        sv = self.mods.skinview
        img = QImage(str(FONDO_IMG)) if FONDO_IMG.exists() else QImage()
        sv.set_imagen(None if img.isNull() else img)
        sv.set_fondo(self.cfg.get("fondo", 0))      # recuerda el fondo que tenías

    def elegir_fondo_img(self, f=""):
        m = self.mods
        if not f:
            f, _ = QFileDialog.getOpenFileName(m, "Elige una imagen de fondo", "",
                                               "Imágenes (*.png *.jpg *.jpeg *.webp *.bmp)")
        if not f:
            return
        img = QImage(f)
        if img.isNull():
            m.skin_msg.setText("No se pudo leer esa imagen.")
            return
        if max(img.width(), img.height()) > FONDO_IMG_MAX:   # más grande no aporta nada y pesa
            img = img.scaled(FONDO_IMG_MAX, FONDO_IMG_MAX, Qt.AspectRatioMode.KeepAspectRatio,
                             Qt.TransformationMode.SmoothTransformation)
        core.ROOT.mkdir(parents=True, exist_ok=True)
        img.save(str(FONDO_IMG), "PNG")
        m.skinview.set_imagen(img)
        self.guardar_config()
        m.skin_msg.setText("Fondo propio aplicado ✓ (se ajusta al tamaño del visor)")

    def quitar_fondo_img(self):
        FONDO_IMG.unlink(missing_ok=True)
        self.mods.skinview.set_imagen(None)
        self.guardar_config()
        self.mods.skin_msg.setText("Imagen de fondo quitada")

    # ---- acceso directo (se comporta como una app instalada)
    def crear_atajos(self):
        j = self.jugar
        j.aviso("Creando acceso directo…", "work")
        try:
            ico_path, png_path = guardar_iconos(core.ROOT / "ui")   # imágenes en el hilo principal
        except Exception as e:  # noqa: BLE001
            j.aviso(f"No se pudo crear el icono: {str(e)[:90]}", "err")
            return
        script = Path(__file__).resolve()

        def work():
            try:
                rutas = core.install_shortcuts(script, ico_path, png_path)
                self.bridge.atajo.emit(True, ", ".join(p.parent.name or str(p.parent) for p in rutas))
            except Exception as e:  # noqa: BLE001
                self.bridge.atajo.emit(False, str(e)[:120])
        threading.Thread(target=work, daemon=True).start()

    def on_atajo(self, ok, detalle):
        j = self.jugar
        if ok:
            self.cfg["atajo_ofrecido"] = True
            self.guardar_config()
            j.mostrar_banner(False)
            j.aviso(f"Acceso directo creado ✓ ({detalle}). Ya puedes abrirlo con su icono.", "ok")
        else:
            j.aviso(f"No se pudo crear el acceso directo: {detalle}", "err")

    def rechazar_atajo(self):
        self.cfg["atajo_ofrecido"] = True
        self.guardar_config()
        self.jugar.mostrar_banner(False)

    # ---- versiones
    def cargar_versiones(self, *_):
        snaps = self.jugar.snapshots.isChecked()
        self.jugar.version.clear(); self.jugar.version.addItem("Cargando versiones…")

        def work():
            try:
                self.bridge.versions.emit([v["id"] for v in core.get_versions(snaps)], True)
            except Exception:
                self.bridge.versions.emit(FALLBACK_VERSIONS, False)
        threading.Thread(target=work, daemon=True).start()

    def on_versiones(self, ids, online):
        if VERSION_POR_DEFECTO not in ids:
            ids = [VERSION_POR_DEFECTO] + ids
        self.jugar.poner_versiones(ids, self.cfg.get("version") or VERSION_POR_DEFECTO)
        if not online:
            self.jugar.aviso("Sin conexión: usando lista de versiones local", "warn")

    # ---- Modrinth
    def contexto(self):
        mc = self.jugar.version.currentText()
        if not mc or mc.startswith("Cargando"):
            mc = self.cfg.get("version") or VERSION_POR_DEFECTO
        return mc, self.jugar.loader.actual()

    def contexto_cambiado(self, *_):
        if self.jugar.version.currentText().startswith("Cargando"):
            return
        mc, loader = self.contexto()
        self.mods.mr_set_contexto(mc, loader)
        self.mr_cargado = False
        if self.mods.cat.actual() == "Modrinth":
            self.mr_timer.start()

    def on_categoria(self, texto):
        if texto == "Modrinth" and not self.mr_cargado:
            self.mr_buscar(self.mods.mr_buscar.text())

    def mr_buscar(self, texto):
        mc, loader = self.contexto()
        self.mr_id += 1
        sid = self.mr_id
        self.mr_cargado = True
        self.mods.mr_estado_set("Buscando en Modrinth…", True, 0.3)

        def work():
            try:
                hits = core.modrinth_search(texto, mc, loader)
            except Exception as e:  # noqa: BLE001
                self.mrb.error.emit(f"No se pudo conectar con Modrinth ({str(e)[:80]}).")
                return
            self.mrb.resultados.emit(sid, hits)
            urls = {i: h["icon_url"] for i, h in enumerate(hits) if h.get("icon_url")}
            with ThreadPoolExecutor(6) as ex:
                futs = {ex.submit(core.fetch_bytes, u): i for i, u in urls.items()}
                for f in as_completed(futs):
                    if sid != self.mr_id:
                        break
                    try:
                        self.mrb.icono.emit(sid, futs[f], f.result())
                    except Exception:  # noqa: BLE001
                        pass
        threading.Thread(target=work, daemon=True).start()

    def on_mr_resultados(self, sid, hits):
        if sid == self.mr_id:
            self.mods.mr_poner_resultados(hits)

    def on_mr_icono(self, sid, fila, datos):
        if sid == self.mr_id:
            self.mods.mr_poner_icono(fila, datos)

    def mr_instalar(self, pid, titulo, categoria):
        if self.mr_instalando:
            return
        mc, loader = self.contexto()
        self.mr_instalando = True
        self.mods.mr_estado_set(f"Instalando {titulo}…", True, 0.05)

        def work():
            try:
                rutas = core.modrinth_install(pid, mc, loader, MODS_LIBRARY, categoria,
                                              lambda f, t: self.mrb.progreso.emit(int(f * 100), t))
                self.mrb.instalado.emit([str(p) for p in rutas], titulo)
            except Exception as e:  # noqa: BLE001
                self.mrb.error.emit(f"No se pudo instalar: {str(e)[:110]}")
        threading.Thread(target=work, daemon=True).start()

    def on_mr_progreso(self, pct, texto):
        self.mods.mr_estado_set(texto, True, pct / 100)

    def on_mr_instalado(self, rutas, titulo):
        self.mr_instalando = False
        rels = []
        for r in rutas:
            try:
                rels.append(Path(r).relative_to(MODS_LIBRARY).as_posix())
            except ValueError:
                pass
        self.mods.cargar_mods(self.mods.mods_seleccionados_rel() + rels)
        deps = max(0, len(rutas) - 1)
        extra = f" (+{deps} dependencia{'s' if deps != 1 else ''})" if deps else ""
        self.mods.mr_estado_set(f"✓ {titulo} instalado{extra} y marcado en Mods.", False, 1.0)

    def on_mr_error(self, msg):
        self.mr_instalando = False
        self.mods.mr_estado_set(msg, False, 0.0)

    # ---- jugar
    def iniciar(self):
        j = self.jugar
        mc = j.version.currentText()
        if self.jugando or not mc or mc.startswith("Cargando"):
            return
        if not USER_RE.fullmatch(j.usuario.text().strip()):
            self.revisar_avisos()
            return
        self.guardar_config()
        loader, user = j.loader.actual(), j.usuario.text().strip()
        ram = int(j.ram.currentText().split()[0])
        mods = self.mods.mods_seleccionados()
        skin = ({"png": str(core.SKIN_FILE), "slim": self.mods.chk_slim.isChecked()}
                if core.SKIN_FILE.exists() else None)
        self.jugando = True
        j.btn.setEnabled(False); j.btn.setText("  P R E P A R A N D O …"); j.barra.setValue(0)
        j.punto.poner("work")
        self.ultimo_log = core.INSTANCES / f"{mc}-{loader.lower()}" / "launcher_output.log"

        def work():
            try:
                cmd, inst = core.prepare(mc, loader, user, ram, mods,
                                         lambda f, t: self.bridge.progress.emit(int(f * 100), t),
                                         skin=skin, library=MODS_LIBRARY)
                log = inst / "launcher_output.log"
                proc = core.launch(cmd, inst, log)
                self.bridge.progress.emit(100, "Esperando a que abra Minecraft…")
                t0 = time.time()
                while time.time() - t0 < 6 and proc.poll() is None:
                    time.sleep(0.25)
                if proc.poll() is not None:  # murió enseguida: mostramos por qué
                    cola = "\n".join(core.tail(log, 4))
                    self.bridge.failed.emit(f"Minecraft se cerró al iniciar (código {proc.returncode}).\n{cola}")
                    return
                core.watch_title(proc)  # ventana: «CeroTouch - versión»
                self.bridge.launched.emit()
                self.bridge.closed.emit(proc.wait(), str(log))
            except Exception as e:  # noqa: BLE001
                self.bridge.failed.emit(str(e))
        threading.Thread(target=work, daemon=True).start()

    def on_progreso(self, pct, texto):
        self.jugar.barra.setValue(pct); self.jugar.pct.setText(f"{pct}%")
        self.jugar.aviso(texto, "work")

    def on_lanzado(self):
        self.jugar.btn.setText("  J U G A N D O")
        self.jugar.aviso("Minecraft está abierto. ¡Disfruta!", "ok")
        self.minimizar()

    def on_cerrado(self, code, log):
        self.terminar()
        self.jugar.showNormal()
        if code == 0:
            self.jugar.aviso("Minecraft se cerró. Listo para jugar", "ok")
        else:
            self.jugar.aviso(f"Minecraft se cerró con error ({code}). Pulsa «Registro».", "err")

    def on_error(self, msg):
        self.terminar()
        self.jugar.aviso(msg, "err")

    def terminar(self):
        self.jugando = False
        self.jugar.btn.setText("  J U G A R")
        self.jugar.barra.setValue(0); self.jugar.pct.setText("")
        self.revisar_avisos()
        self.actualizar_pie()

    def abrir_registro(self):
        j = self.jugar
        log = getattr(self, "ultimo_log", None) or (
            core.INSTANCES / f"{j.version.currentText()}-{j.loader.actual().lower()}" / "launcher_output.log")
        if log.exists():
            os.startfile(log) if core.OS_NAME == "windows" else core.open_folder(log.parent)
        else:
            j.aviso("Aún no hay registro para esta versión.", "warn")


if __name__ == "__main__":
    if sys.stderr is None or sys.stdout is None:        # abierto con pythonw (sin consola): guardamos los errores
        try:
            core.ROOT.mkdir(parents=True, exist_ok=True)
            _log = open(core.ROOT / "errores.log", "a", encoding="utf-8")
            sys.stdout = sys.stdout or _log
            sys.stderr = sys.stderr or _log
        except Exception:
            pass
    if core.OS_NAME == "windows":                       # para que la barra de tareas use NUESTRO icono
        try:
            import ctypes
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("CeroTouch.Launcher")
        except Exception:
            pass
    if "--crear-acceso-directo" in sys.argv:            # lo usa Iniciar_CeroTouch.bat (sin abrir ventana)
        qt = QApplication(sys.argv)
        try:
            _ico, _png = guardar_iconos(core.ROOT / "ui")
            _rutas = core.install_shortcuts(Path(__file__).resolve(), _ico, _png)
            print("Acceso directo creado:")
            for _r in _rutas:
                print("  ", _r)
            sys.exit(0)
        except Exception as e:  # noqa: BLE001
            print("ERROR:", e)
            sys.exit(1)
    qt = QApplication(sys.argv)
    qt.setApplicationName("CeroTouch Launcher")
    qt.setWindowIcon(logo_icon())
    qt.setStyleSheet(STYLE.replace("ARROW", make_arrow_png()))
    app = App()
    app.mostrar()
    sys.exit(qt.exec())