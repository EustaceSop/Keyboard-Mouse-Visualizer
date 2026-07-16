import sys
import json
import os
from PyQt5.QtWidgets import (QApplication, QWidget, QLabel, QGridLayout, 
                             QVBoxLayout, QHBoxLayout, QSystemTrayIcon, QMenu, QAction,
                             QActionGroup, QGraphicsDropShadowEffect)
from PyQt5.QtCore import Qt, pyqtSignal, QObject, QTimer, QPoint
from PyQt5.QtGui import QIcon, QPainter, QColor, QFont
from pynput import keyboard, mouse

# 設定檔路徑
CONFIG_FILE = "overlay_config.json"

# ---- 主題定義：每個主題提供 (base, pressed) 兩種樣式表 ----
THEMES = {
    "neon": {
        "label": "霓虹發光",
        "font": "Segoe UI",
        "base": """
            background-color: rgba(15, 18, 30, 0.72);
            color: #7fe7ff;
            border: 1px solid rgba(0, 200, 255, 0.35);
            border-radius: 8px;
        """,
        "pressed": """
            background-color: rgba(0, 225, 255, 0.9);
            color: #06121a;
            border: 1px solid #b6f7ff;
            border-radius: 8px;
        """,
        "mouse": {
            "body":     (15, 18, 30, 200),
            "outline":  (0, 200, 255, 110),
            "divider":  (0, 200, 255, 90),
            "fill":     (40, 55, 80, 160),
            "pressed":  (0, 225, 255, 230),
            "text":     (127, 231, 255, 255),
            "text_hi":  (6, 18, 26, 255),
        },
    },
    "glass": {
        "label": "毛玻璃",
        "font": "Segoe UI",
        "base": """
            background-color: rgba(255, 255, 255, 0.08);
            color: rgba(255, 255, 255, 0.82);
            border: 1px solid rgba(255, 255, 255, 0.18);
            border-radius: 10px;
        """,
        "pressed": """
            background-color: rgba(255, 255, 255, 0.85);
            color: #1c1c22;
            border: 1px solid rgba(255, 255, 255, 0.95);
            border-radius: 10px;
        """,
        "mouse": {
            "body":     (255, 255, 255, 22),
            "outline":  (255, 255, 255, 60),
            "divider":  (255, 255, 255, 45),
            "fill":     (255, 255, 255, 20),
            "pressed":  (255, 255, 255, 210),
            "text":     (255, 255, 255, 210),
            "text_hi":  (28, 28, 34, 255),
        },
    },
    "keycap": {
        "label": "鍵帽擬真",
        "font": "Consolas",
        "base": """
            background-color: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                stop:0 #4a4a52, stop:1 #2a2a30);
            color: #e8e8ec;
            border: 1px solid #1a1a1e;
            border-top: 1px solid #6a6a72;
            border-radius: 7px;
        """,
        "pressed": """
            background-color: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                stop:0 #ffd75e, stop:1 #f0a500);
            color: #201800;
            border: 1px solid #7a5500;
            border-radius: 7px;
        """,
        "mouse": {
            "body":     (58, 58, 66, 235),
            "outline":  (26, 26, 30, 255),
            "divider":  (20, 20, 24, 255),
            "fill":     (74, 74, 82, 200),
            "pressed":  (240, 165, 0, 240),
            "text":     (232, 232, 236, 255),
            "text_hi":  (32, 24, 0, 255),
        },
    },
}

# 定義訊號類別，用於將 pynput 的背景執行緒事件傳遞給 PyQt 的主執行緒
class InputSignals(QObject):
    key_event = pyqtSignal(str, bool)      # key_name, is_pressed
    mouse_event = pyqtSignal(str, bool)    # button_name, is_pressed
    scroll_event = pyqtSignal(str)         # direction (up/down)

signals = InputSignals()


class MouseWidget(QWidget):
    """自訂繪製的滑鼠圖形，取代原本的方格排版。"""

    # 五個可高亮的區域名稱
    REGIONS = ('Mouse_L', 'Mouse_R', 'Mouse_M', 'Side 1', 'Side 2')

    def __init__(self, get_theme, parent=None):
        super().__init__(parent)
        self.get_theme = get_theme          # callable -> 目前主題的 mouse 色盤
        self.pressed = {r: False for r in self.REGIONS}
        self.setFixedSize(110, 170)
        self.setAttribute(Qt.WA_TransparentForMouseEvents)

    def set_pressed(self, region, is_pressed):
        if region in self.pressed:
            self.pressed[region] = is_pressed
            self.update()

    def _c(self, rgba):
        return QColor(*rgba)

    def paintEvent(self, event):
        from PyQt5.QtGui import QPainterPath
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        pal = self.get_theme()

        w, h = self.width(), self.height()
        m = 6
        body = self.rect().adjusted(m, m, -m, -m)

        # 滑鼠外殼（上半圓弧、下半圓角）
        path = QPainterPath()
        rx = body.width() * 0.5
        top = body.top()
        left = body.left()
        right = body.right()
        bottom = body.bottom()
        midx = body.center().x()
        path.moveTo(left, top + body.height() * 0.42)
        path.cubicTo(left, top, right, top, right, top + body.height() * 0.42)
        path.lineTo(right, bottom - rx * 0.5)
        path.cubicTo(right, bottom, left, bottom, left, bottom - rx * 0.5)
        path.closeSubpath()

        p.setPen(QColor(*pal["outline"]))
        p.setBrush(QColor(*pal["body"]))
        p.drawPath(path)

        # 用外殼路徑當裁切區，讓內部分區不超出邊界
        p.setClipPath(path)

        split_y = top + body.height() * 0.46   # 左右鍵與下半身分界
        # 左鍵
        self._fill_rect(p, pal, 'Mouse_L', left, top, midx - 8, split_y)
        # 右鍵
        self._fill_rect(p, pal, 'Mouse_R', midx + 8, top, right, split_y)
        # 中鍵/滾輪
        wheel_w = 14
        self._fill_round(p, pal, 'Mouse_M',
                         midx - wheel_w / 2, top + 14,
                         midx + wheel_w / 2, top + 46, r=7)

        p.setClipping(False)

        # 分隔線
        p.setPen(QColor(*pal["divider"]))
        p.drawLine(int(midx), int(top + 4), int(midx), int(split_y - 2))
        p.drawLine(int(left + 2), int(split_y), int(right - 2), int(split_y))

        # 側鍵（畫在左側外緣的兩顆小鈕）
        self._fill_round(p, pal, 'Side 1', left - 3, top + 52, left + 12, top + 68, r=4)
        self._fill_round(p, pal, 'Side 2', left - 3, top + 72, left + 12, top + 88, r=4)

        # 文字標籤
        p.setFont(QFont(pal.get("font", "Segoe UI"), 8, QFont.Bold))
        self._label(p, pal, 'Mouse_L', 'L', left, top, midx, split_y)
        self._label(p, pal, 'Mouse_R', 'R', midx, top, right, split_y)

    def _fill_rect(self, p, pal, region, x1, y1, x2, y2):
        color = pal["pressed"] if self.pressed[region] else pal["fill"]
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(*color))
        p.drawRect(int(x1), int(y1), int(x2 - x1), int(y2 - y1))

    def _fill_round(self, p, pal, region, x1, y1, x2, y2, r=6):
        color = pal["pressed"] if self.pressed[region] else pal["fill"]
        p.setPen(QColor(*pal["divider"]))
        p.setBrush(QColor(*color))
        p.drawRoundedRect(int(x1), int(y1), int(x2 - x1), int(y2 - y1), r, r)

    def _label(self, p, pal, region, text, x1, y1, x2, y2):
        color = pal["text_hi"] if self.pressed[region] else pal["text"]
        p.setPen(QColor(*color))
        from PyQt5.QtCore import QRectF
        p.drawText(QRectF(x1, y1, x2 - x1, y2 - y1), Qt.AlignCenter, text)


class OverlayWidget(QWidget):
    def __init__(self):
        super().__init__()
        self.config = self.load_config()
        self.is_dragging = False
        self.drag_pos = QPoint()
        
        self.init_ui()
        self.init_tray()
        self.setup_listeners()
        
    def load_config(self):
        default_config = {"x": 100, "y": 100, "mode": "minimal", "theme": "neon"}
        if os.path.exists(CONFIG_FILE):
            try:
                with open(CONFIG_FILE, 'r') as f:
                    cfg = json.load(f)
                    default_config.update(cfg)
            except:
                pass
        if default_config.get("theme") not in THEMES:
            default_config["theme"] = "neon"
        return default_config

    def save_config(self):
        self.config["x"] = self.x()
        self.config["y"] = self.y()
        with open(CONFIG_FILE, 'w') as f:
            json.dump(self.config, f)

    def init_ui(self):
        # 設定懸浮、無邊框、置頂、背景透明
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground)
        
        # 主排版
        self.layout = QHBoxLayout(self)
        self.layout.setContentsMargins(10, 10, 10, 10)
        self.layout.setSpacing(12)
        self.keys_dict = {}    # 儲存按鍵與對應的 QLabel
        self.pressed_state = {}  # 記錄每顆鍵的按下狀態，供切換主題時重繪
        
        self.build_keyboard_ui()
        self.build_mouse_ui()
        
        self.move(self.config["x"], self.config["y"])
        
        # 綁定訊號
        signals.key_event.connect(self.update_key)
        signals.mouse_event.connect(self.update_key)
        signals.scroll_event.connect(self.update_scroll)

    def create_key_label(self, text, width=40, height=40, key_id=None):
        lbl = QLabel(text)
        lbl.setFixedSize(width, height)
        lbl.setAlignment(Qt.AlignCenter)
        lbl.setFont(QFont(THEMES[self.config["theme"]]["font"], 10, QFont.Bold))
        lbl.setAttribute(Qt.WA_TransparentForMouseEvents) 
        
        # 如果有給 key_id 就用 key_id，否則就用顯示的 text
        dict_key = key_id if key_id else text 
        
        self.keys_dict[dict_key] = lbl
        self.pressed_state[dict_key] = False
        self.set_label_style(lbl, False)
        return lbl

    def set_label_style(self, lbl, is_pressed):
        theme = THEMES[self.config["theme"]]
        lbl.setStyleSheet(theme["pressed"] if is_pressed else theme["base"])

    def apply_theme(self, theme_name):
        if theme_name not in THEMES:
            return
        self.config["theme"] = theme_name
        font_name = THEMES[theme_name]["font"]
        for dict_key, lbl in self.keys_dict.items():
            f = lbl.font()
            f.setFamily(font_name)
            lbl.setFont(f)
            self.set_label_style(lbl, self.pressed_state.get(dict_key, False))
        self.mouse_widget.update()  # 重繪滑鼠圖形套用新主題
        self.save_config()

    def build_keyboard_ui(self):
        self.kb_widget = QWidget()
        grid = QGridLayout(self.kb_widget)
        grid.setSpacing(2)
        
        # 常用按鍵排版 (可以依據需求擴充此陣列)
        # 這裡示範 WASD 及周邊
        row1 = [('Q',0), ('W',1), ('E',2), ('R',3)]
        row2 = [('A',0), ('S',1), ('D',2), ('F',3)]
        
        for key, col in row1: grid.addWidget(self.create_key_label(key), 0, col)
        for key, col in row2: grid.addWidget(self.create_key_label(key), 1, col)
        
        # 特殊按鍵
        grid.addWidget(self.create_key_label('Shift', 80, 40), 2, 0, 1, 2)
        grid.addWidget(self.create_key_label('Ctrl', 80, 40), 2, 2, 1, 2)
        grid.addWidget(self.create_key_label('Space', 165, 30), 3, 0, 1, 4)
        
        self.layout.addWidget(self.kb_widget)

    def build_mouse_ui(self):
        # 用自訂繪製的滑鼠圖形取代方格
        self.mouse_widget = MouseWidget(
            get_theme=lambda: {**THEMES[self.config["theme"]]["mouse"],
                               "font": THEMES[self.config["theme"]]["font"]}
        )
        self.layout.addWidget(self.mouse_widget, alignment=Qt.AlignVCenter)

    def init_tray(self):
        # 建立系統列圖示 (這裡產生一個簡單的黑色方塊作為預設圖示)
        self.tray_icon = QSystemTrayIcon(self)
        pixmap = QPainter().device()
        icon_img = QColor(50, 50, 50)
        self.tray_icon.setIcon(self.style().standardIcon(self.style().SP_ComputerIcon))
        
        # 菜單
        tray_menu = QMenu()
        
        toggle_action = QAction("顯示/隱藏視窗", self)
        toggle_action.triggered.connect(self.toggle_visibility)
        tray_menu.addAction(toggle_action)
        
        # 風格切換子選單
        theme_menu = tray_menu.addMenu("切換風格")
        theme_group = QActionGroup(self)
        theme_group.setExclusive(True)
        for name, meta in THEMES.items():
            act = QAction(meta["label"], self, checkable=True)
            act.setChecked(name == self.config["theme"])
            act.triggered.connect(lambda _, n=name: self.apply_theme(n))
            theme_group.addAction(act)
            theme_menu.addAction(act)
        
        tray_menu.addSeparator()
        quit_action = QAction("離開", self)
        quit_action.triggered.connect(self.quit_app)
        tray_menu.addAction(quit_action)
        
        self.tray_icon.setContextMenu(tray_menu)
        self.tray_icon.show()

    def toggle_visibility(self):
        if self.isVisible():
            self.hide()
        else:
            self.show()

    def quit_app(self):
        self.save_config()
        QApplication.quit()

    # --- UI 更新邏輯 ---
    def update_key(self, key_name, is_pressed):
        # 滑鼠區域交給自訂繪製的 MouseWidget
        if key_name in MouseWidget.REGIONS:
            self.mouse_widget.set_pressed(key_name, is_pressed)
            return
        if key_name in self.keys_dict:
            self.pressed_state[key_name] = is_pressed
            self.set_label_style(self.keys_dict[key_name], is_pressed)

    def update_scroll(self, direction):
        # 滾動時讓中鍵/滾輪短暫高亮 (滾輪沒有 Release 事件)
        self.mouse_widget.set_pressed('Mouse_M', True)
        QTimer.singleShot(150, lambda: self.mouse_widget.set_pressed('Mouse_M', False))

    # --- 拖曳視窗邏輯 ---
    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.is_dragging = True
            self.drag_pos = event.globalPos() - self.frameGeometry().topLeft()
            event.accept()

    def mouseMoveEvent(self, event):
        if event.buttons() == Qt.LeftButton and self.is_dragging:
            self.move(event.globalPos() - self.drag_pos)
            event.accept()

    def mouseReleaseEvent(self, event):
        self.is_dragging = False
        self.save_config() # 拖曳結束時自動存檔位置

    # --- Pynput 監聽器設定 ---
    def setup_listeners(self):
        def on_press(key):
            key_name = self.get_key_name(key)
            if key_name: signals.key_event.emit(key_name, True)

        def on_release(key):
            key_name = self.get_key_name(key)
            if key_name: signals.key_event.emit(key_name, False)

        def on_click(x, y, button, pressed):
            btn_name = self.get_mouse_btn_name(button)
            if btn_name: signals.mouse_event.emit(btn_name, pressed)

        def on_scroll(x, y, dx, dy):
            direction = 'up' if dy > 0 else 'down'
            signals.scroll_event.emit(direction)

        self.kb_listener = keyboard.Listener(on_press=on_press, on_release=on_release)
        self.ms_listener = mouse.Listener(on_click=on_click, on_scroll=on_scroll)
        self.kb_listener.start()
        self.ms_listener.start()

    def get_key_name(self, key):
        # 解析按鍵名稱以對應 UI 的 Label 文字
        try:
            if hasattr(key, 'char') and key.char:
                return key.char.upper()
            
            # 特殊按鍵映射
            special_keys = {
                keyboard.Key.shift: 'Shift',
                keyboard.Key.shift_r: 'Shift',
                keyboard.Key.space: 'Space',
                keyboard.Key.ctrl: 'Ctrl',
                keyboard.Key.ctrl_l: 'Ctrl',
                keyboard.Key.ctrl_r: 'Ctrl',
                # 可以在這裡加入 alt, tab 等
            }
            return special_keys.get(key, None)
        except:
            return None

    def get_mouse_btn_name(self, button):
        btn_map = {
            mouse.Button.left: 'Mouse_L',
            mouse.Button.right: 'Mouse_R',
            mouse.Button.middle: 'Mouse_M',
            mouse.Button.x1: 'Side 1', 
            mouse.Button.x2: 'Side 2'  
        }
        return btn_map.get(button, None)

if __name__ == "__main__":
    # 這裡的 sys.args 必須改成 sys.argv
    app = QApplication(sys.argv)
    
    # 確保應用程式不會因為關閉懸浮視窗就結束 (由系統列控制)
    app.setQuitOnLastWindowClosed(False) 
    
    overlay = OverlayWidget()
    overlay.show()
    
    sys.exit(app.exec_())