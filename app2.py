# -*- coding: utf-8 -*-
"""
InouT – 4-Camera Live Viewer (no ffmpeg)
---------------------------------------
• Shows a splash screen with the InouT logo
• Asks for 4 camera IPs (HTTP / RTSP / files)
• Displays up to 4 video streams in a 2x2 grid
• Uses OpenCV + PySide6 (no ffmpeg)
"""

import sys
from pathlib import Path
from typing import List, Optional

import cv2
import numpy as np
from PySide6 import QtCore, QtGui, QtWidgets


# ====================== Worker Thread ======================

class VideoWorker(QtCore.QThread):
    frame_ready = QtCore.Signal(int, QtGui.QImage)
    error = QtCore.Signal(int, str)

    def __init__(self, cam_index: int, source: str, parent=None):
        super().__init__(parent)
        self.cam_index = cam_index
        self.source = source
        self._running = False
        self._cap: Optional[cv2.VideoCapture] = None

    def run(self):
        self._running = True
        self._cap = cv2.VideoCapture(self.source)

        if not self._cap.isOpened():
            self.error.emit(self.cam_index, f"[X] Cannot open video: {self.source}")
            return

        while self._running:
            ok, frame = self._cap.read()
            if not ok:
                self.error.emit(self.cam_index, f"[X] Cannot read frame from: {self.source}")
                break

            # Convert BGR -> RGB
            frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            h, w, ch = frame_rgb.shape
            bytes_per_line = ch * w
            img = QtGui.QImage(
                frame_rgb.data, w, h, bytes_per_line, QtGui.QImage.Format_RGB888
            )
            self.frame_ready.emit(self.cam_index, img)

            # Small sleep so we don’t eat 100% CPU
            if self._cap.get(cv2.CAP_PROP_FPS) > 0:
                self.msleep(int(1000 / self._cap.get(cv2.CAP_PROP_FPS)))
            else:
                self.msleep(15)

        if self._cap is not None:
            self._cap.release()

    def stop(self):
        self._running = False
        self.wait(500)


# ====================== Camera IP Dialog ======================

class InputDialog(QtWidgets.QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("InouT – Camera IPs")
        self.setModal(True)

        self.edits: List[QtWidgets.QLineEdit] = []

        layout = QtWidgets.QFormLayout(self)

        # Default demo values (you can change them)
        defaults = [
            "10.0.0.121:8080",
            "10.0.0.122:8080",
            "10.0.0.123:8080",
            "10.0.0.124:8080",
        ]

        for i in range(4):
            edit = QtWidgets.QLineEdit(self)
            edit.setPlaceholderText(defaults[i])
            layout.addRow(f"Camera {i + 1}", edit)
            self.edits.append(edit)

        btn_ok = QtWidgets.QPushButton("OK", self)
        btn_cancel = QtWidgets.QPushButton("Cancel", self)
        btn_ok.clicked.connect(self.accept)
        btn_cancel.clicked.connect(self.reject)

        btn_layout = QtWidgets.QHBoxLayout()
        btn_layout.addStretch(1)
        btn_layout.addWidget(btn_ok)
        btn_layout.addWidget(btn_cancel)

        layout.addRow(btn_layout)

    def get_urls(self) -> List[str]:
        urls: List[str] = []
        for edit in self.edits:
            txt = edit.text().strip()
            if txt == "":
                urls.append("")
            else:
                # If user only typed IP:port, assume Android IP Webcam style URL
                if txt.startswith("http://") or txt.startswith("rtsp://"):
                    urls.append(txt)
                else:
                    urls.append(f"http://{txt}/video")
        return urls


# ====================== Main Window ======================

class MainWindow(QtWidgets.QMainWindow):
    def __init__(self, urls: List[str], logo_path: Path, parent=None):
        super().__init__(parent)

        self.setWindowTitle("InouT – 4-Cam Live (no ffmpeg)")
        self.resize(1280, 720)

        if logo_path.exists():
            self.setWindowIcon(QtGui.QIcon(str(logo_path)))

        self.urls = urls
        self.workers: List[VideoWorker] = []

        central = QtWidgets.QWidget(self)
        self.setCentralWidget(central)

        main_layout = QtWidgets.QVBoxLayout(central)

        # Top control bar
        ctrl_layout = QtWidgets.QHBoxLayout()
        self.btn_start = QtWidgets.QPushButton("Start", self)
        self.btn_stop = QtWidgets.QPushButton("Stop", self)
        self.btn_stop.setEnabled(False)

        ctrl_layout.addWidget(self.btn_start)
        ctrl_layout.addWidget(self.btn_stop)
        ctrl_layout.addStretch(1)

        main_layout.addLayout(ctrl_layout)

        # 2x2 grid for cameras
        grid = QtWidgets.QGridLayout()
        self.labels: List[QtWidgets.QLabel] = []

        for i in range(4):
            lbl = QtWidgets.QLabel(self)
            lbl.setAlignment(QtCore.Qt.AlignCenter)
            lbl.setStyleSheet("background-color: #202020; color: #AAAAAA;")
            lbl.setText(f"Camera {i + 1}\n(no signal)")
            lbl.setMinimumSize(320, 180)
            self.labels.append(lbl)
            grid.addWidget(lbl, i // 2, i % 2)

        main_layout.addLayout(grid)

        # Status bar
        self.status = self.statusBar()
        self.status.showMessage("Ready")

        # Connections
        self.btn_start.clicked.connect(self.start_streams)
        self.btn_stop.clicked.connect(self.stop_streams)

    # -------------- streaming control --------------

    def start_streams(self):
        self.stop_streams()  # clean up any previous

        for i, url in enumerate(self.urls):
            if not url:
                self.labels[i].setText(f"Camera {i + 1}\n(empty URL)")
                continue

            w = VideoWorker(i, url, self)
            w.frame_ready.connect(self.on_frame_ready)
            w.error.connect(self.on_worker_error)
            self.workers.append(w)
            w.start()

        self.btn_start.setEnabled(False)
        self.btn_stop.setEnabled(True)
        self.status.showMessage("Streaming...")

    def stop_streams(self):
        for w in self.workers:
            w.stop()
        self.workers.clear()

        # Reset labels
        for i, lbl in enumerate(self.labels):
            lbl.setPixmap(QtGui.QPixmap())
            lbl.setText(f"Camera {i + 1}\n(stopped)")

        self.btn_start.setEnabled(True)
        self.btn_stop.setEnabled(False)
        self.status.showMessage("Stopped")

    # -------------- slots --------------

    @QtCore.Slot(int, QtGui.QImage)
    def on_frame_ready(self, cam_index: int, img: QtGui.QImage):
        if 0 <= cam_index < len(self.labels):
            pix = QtGui.QPixmap.fromImage(img)
            self.labels[cam_index].setPixmap(
                pix.scaled(
                    self.labels[cam_index].size(),
                    QtCore.Qt.KeepAspectRatio,
                    QtCore.Qt.SmoothTransformation,
                )
            )

    @QtCore.Slot(int, str)
    def on_worker_error(self, cam_index: int, msg: str):
        if 0 <= cam_index < len(self.labels):
            self.labels[cam_index].setPixmap(QtGui.QPixmap())
            self.labels[cam_index].setText(f"Camera {cam_index + 1}\nError")
        self.status.showMessage(msg)
        print(msg)

    # -------------- close event --------------

    def closeEvent(self, event: QtGui.QCloseEvent) -> None:
        self.stop_streams()
        return super().closeEvent(event)


# ====================== ENTRY POINT ======================

if __name__ == "__main__":
    app = QtWidgets.QApplication(sys.argv)
    app.setOrganizationName("InouT")
    app.setApplicationName("TennisInouT – 4-Cam Live (no ffmpeg)")

    BASE_DIR = Path(__file__).resolve().parent
    LOGO_PATH = BASE_DIR / "Logo" / "InouTLogo.png"

    print("LOGO_PATH =", LOGO_PATH, "exists?", LOGO_PATH.exists())

    # Splash screen
    if LOGO_PATH.exists():
        pix_orig = QtGui.QPixmap(str(LOGO_PATH))
        if not pix_orig.isNull():
            pix = pix_orig.scaled(
                480,
                480,
                QtCore.Qt.KeepAspectRatio,
                QtCore.Qt.SmoothTransformation,
            )
            splash = QtWidgets.QSplashScreen(pix)
            splash.show()
            QtWidgets.QApplication.processEvents()
            QtCore.QThread.msleep(1200)
            splash.close()

        # Set window icon for all top-level windows
        app.setWindowIcon(QtGui.QIcon(str(LOGO_PATH)))

    # Ask for camera URLs
    dlg = InputDialog()
    if dlg.exec() != QtWidgets.QDialog.Accepted:
        sys.exit(0)

    urls = dlg.get_urls()

    win = MainWindow(urls, LOGO_PATH)
    win.show()

    sys.exit(app.exec())
