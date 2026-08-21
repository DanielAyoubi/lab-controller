import sys
from PyQt6.QtWidgets import QApplication
from src.gui.main_window import MainWindow


def main():
    # Device tags are free text and reach the console through the drivers'
    # status prints. A Windows console defaults to cp1252, where a tag like
    # "O₂ line" would raise UnicodeEncodeError mid-connect.
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            try:
                stream.reconfigure(encoding="utf-8", errors="replace")
            except Exception:
                pass

    app = QApplication(sys.argv)

    # Set style
    app.setStyle("Fusion")

    window = MainWindow()
    # Maximised rather than showFullScreen(): the plot wants all the width it
    # can get, but a lab app still needs its title bar and the taskbar.
    window.showMaximized()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
