import cv2
import re
import numpy as np
import tkinter as tk
from tkinter import filedialog, messagebox
from PIL import Image, ImageTk
import threading
import os
import time
 
# ─── KHỞI TẠO EASYOCR ────────────────────────────────────────────────────────
try:
    import easyocr
    READER = easyocr.Reader(['en'], verbose=False)
except ImportError:
    READER = None
 
# ─── DANH SÁCH TỪ KHÔNG PHẢI BIỂN SỐ ────────────────────────────────────────
NON_PLATE_WORDS = {
    "POLIS", "POLICE", "POLISI", "TAXI", "BUS", "STOP", "SPEED", "EXIT",
    "ENTER", "SLOW", "ROAD", "ZONE", "LIMIT", "MAX", "KMH", "MPH",
    "AMBULANCE", "FIRE", "TRUCK", "CARGO", "SCHOOL", "WARNING",
    "CAUTION", "DANGER", "DIESEL", "PETROL", "HONDA", "TOYOTA",
    "HYUNDAI", "FORD", "SUZUKI", "YAMAHA"
}
 
# ─── REGEX BIỂN SỐ VIỆT NAM ──────────────────────────────────────────────────
# VD: 51G-123.45 | 43A-272.08 | 30F1-2345 | 29A-12345
PLATE_PATTERNS = [
    r'^\d{2}[A-Z]\d?[-.]?\d{3,4}[.-]?\d{2}$',
    r'^\d{2}[A-Z]{1,2}[-.]?\d{4,6}$',
]
 
def is_plate_format(text: str) -> bool:
    t = text.upper().replace(" ", "").replace("O", "0").replace("I", "1")
    for pat in PLATE_PATTERNS:
        if re.match(pat, t):
            return True
    return False
 
def score_candidate(text: str, bbox, frame_shape) -> float:
    """Chấm điểm mỗi vùng chữ — điểm cao nhất = biển số được chọn."""
    clean = "".join(c for c in text if c.isalnum() or c in "-.")
    upper = clean.upper()
    score = 0.0
 
    # ── Trừ điểm nặng nếu là từ thông thường ──
    if upper in NON_PLATE_WORDS:
        return -999
    # Trừ nếu toàn chữ cái (không có số) → không phải biển số
    if clean.isalpha() and len(clean) <= 8:
        score -= 60
 
    # ── Cộng điểm mạnh nếu khớp định dạng biển số VN ──
    if is_plate_format(clean):
        score += 100
 
    # ── Vị trí: ưu tiên nửa dưới khung hình ──
    h = frame_shape[0]
    (tl, tr, br, bl) = bbox
    center_y = (tl[1] + br[1]) / 2
    if center_y > h * 0.4:
        score += 15
 
    # ── Tỷ lệ w/h: biển số thật ~3:1 đến 6:1 ──
    box_w = abs(br[0] - tl[0])
    box_h = abs(br[1] - tl[1]) + 1e-5
    ratio = box_w / box_h
    if 2.5 <= ratio <= 7.0:
        score += 20
    elif ratio > 12:
        score -= 25
 
    # ── Độ dài chuỗi: biển số VN thường 7–11 ký tự ──
    n = len(clean)
    if 6 <= n <= 12:
        score += 10
    elif n > 15:
        score -= 20
 
    return score
 
 
# ─── HÀM NHẬN DIỆN CHÍNH ─────────────────────────────────────────────────────
def detect_and_annotate(frame):
    if READER is None:
        return frame, "Chưa cài EasyOCR", None
 
    result_img = frame.copy()
    h, w = frame.shape[:2]
 
    results = READER.readtext(frame)
 
    best_score = -999
    best_text  = ""
    best_bbox  = None
 
    for (bbox, text, prob) in results:
        if prob < 0.2:
            continue
        clean = "".join(c for c in text if c.isalnum() or c in "-.")
        if len(clean) < 4:
            continue
 
        # Tổng điểm = điểm hình dạng + thưởng theo độ tin cậy OCR
        s = score_candidate(clean, bbox, frame.shape) + prob * 20
 
        if s > best_score:
            best_score = s
            best_text  = clean
            best_bbox  = bbox
 
    plate_img = None
 
    # Chỉ vẽ nếu điểm đủ cao (tránh vẽ bừa khi không tìm thấy biển số)
    if best_bbox is not None and best_score > -10:
        (tl, tr, br, bl) = best_bbox
        tl = (int(tl[0]), int(tl[1]))
        br = (int(br[0]), int(br[1]))
 
        plate_img = frame[max(0, tl[1]-5):min(h, br[1]+5),
                          max(0, tl[0]-5):min(w, br[0]+5)]
 
        cv2.rectangle(result_img, tl, br, (0, 255, 0), 3)
        cv2.putText(result_img, best_text, (tl[0], tl[1] - 10),
                    cv2.FONT_HERSHEY_SIMPLEX, 1.2, (0, 255, 0), 3)
    else:
        best_text = ""
 
    return result_img, best_text, plate_img
 
 
# ─── GIAO DIỆN NGƯỜI DÙNG ────────────────────────────────────────────────────
class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("🚗 HỆ THỐNG NHẬN DIỆN BIỂN SỐ XE")
        self.state('zoomed')
        self.configure(bg="#0d1117")
        self._cap     = None
        self._running = False
        self._build_ui()
        self.protocol("WM_DELETE_WINDOW", self._on_close)
 
    def _build_ui(self):
        hdr = tk.Frame(self, bg="#0d1117")
        hdr.pack(fill="x", padx=20, pady=10)
        tk.Label(hdr, text="🚗 AI LICENSE PLATE RECOGNITION",
                 font=("Arial", 24, "bold"), fg="#00e5ff", bg="#0d1117").pack(side="left")
 
        bar = tk.Frame(self, bg="#161b22", pady=10)
        bar.pack(fill="x", padx=20)
        btn_s = {"font": ("Arial", 10, "bold"), "fg": "white",
                 "width": 12, "bd": 0, "cursor": "hand2"}
        tk.Button(bar, text="📂 MỞ ẢNH",  command=self._open_image,  bg="#1f6feb", **btn_s).pack(side="left", padx=5)
        tk.Button(bar, text="🎬 VIDEO",   command=self._open_video,  bg="#238636", **btn_s).pack(side="left", padx=5)
        tk.Button(bar, text="📷 WEBCAM",  command=self._open_webcam, bg="#9e6a03", **btn_s).pack(side="left", padx=5)
        tk.Button(bar, text="⏹ DỪNG",    command=self._stop,        bg="#b62324", **btn_s).pack(side="left", padx=5)
 
        main_frame = tk.Frame(self, bg="#0d1117")
        main_frame.pack(fill="both", expand=True, padx=20, pady=10)
 
        self._video_container = tk.Frame(main_frame, bg="black")
        self._video_container.pack(side="left", fill="both", expand=True)
 
        self._video_lbl = tk.Label(self._video_container, bg="black")
        self._video_lbl.place(relx=0.5, rely=0.5, anchor="center")
 
        right_panel = tk.Frame(main_frame, bg="#161b22", width=350)
        right_panel.pack(side="right", fill="y", padx=(15, 0))
        right_panel.pack_propagate(False)
 
        tk.Label(right_panel, text="KẾT QUẢ CHI TIẾT",
                 font=("Arial", 12), fg="#8b949e", bg="#161b22").pack(pady=20)
        self._plate_lbl = tk.Label(right_panel, bg="#010409", width=300, height=150)
        self._plate_lbl.pack(padx=10)
 
        self._result_var = tk.StringVar(value="SẴN SÀNG")
        tk.Label(right_panel, textvariable=self._result_var,
                 font=("Courier", 28, "bold"), fg="#00e5ff", bg="#161b22").pack(pady=40)
 
    def _show_frame(self, frame):
        if frame is None:
            return
        self.update_idletasks()
        cw = self._video_container.winfo_width()
        ch = self._video_container.winfo_height()
        if cw < 100:
            cw, ch = 1000, 600
        img = Image.fromarray(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
        img = img.resize((cw, ch), Image.Resampling.LANCZOS)
        self._photo = ImageTk.PhotoImage(image=img)
        self._video_lbl.config(image=self._photo)
 
    def _open_image(self):
        self._stop()
        path = filedialog.askopenfilename()
        if path:
            img = cv2.imdecode(np.fromfile(path, dtype=np.uint8), cv2.IMREAD_COLOR)
            if img is not None:
                self._result_var.set("ĐANG QUÉT...")
                self.update()
                annotated, text, plate = detect_and_annotate(img)
                self._show_frame(annotated)
                self._result_var.set(text if text else "KHÔNG THẤY")
                if plate is not None and plate.size > 0:
                    p_img = Image.fromarray(cv2.cvtColor(plate, cv2.COLOR_BGR2RGB)).resize((300, 100))
                    self._plate_photo = ImageTk.PhotoImage(p_img)
                    self._plate_lbl.config(image=self._plate_photo)
 
    def _open_video(self):
        path = filedialog.askopenfilename()
        if path:
            self._start_thread(path)
 
    def _open_webcam(self):
        self._start_thread(0)
 
    def _start_thread(self, source):
        self._stop()
        self._cap     = cv2.VideoCapture(source)
        self._running = True
        self._thread  = threading.Thread(target=self._video_loop, daemon=True)
        self._thread.start()
 
    def _video_loop(self):
        frame_count = 0
        while self._running and self._cap.isOpened():
            ret, frame = self._cap.read()
            if not ret:
                break
            frame_count += 1
 
            if frame_count % 5 == 0:
                # Nhận diện mỗi 5 frame để không bị lag
                annotated, text, plate = detect_and_annotate(frame)
                self.after(0, self._show_frame, annotated)
                if text:
                    self.after(0, self._result_var.set, text)
                    if plate is not None and plate.size > 0:
                        def _update(p=plate):
                            p_img = Image.fromarray(
                                cv2.cvtColor(p, cv2.COLOR_BGR2RGB)
                            ).resize((300, 100))
                            self._plate_photo = ImageTk.PhotoImage(p_img)
                            self._plate_lbl.config(image=self._plate_photo)
                        self.after(0, _update)
            else:
                self.after(0, self._show_frame, frame)
 
            time.sleep(0.01)
        self._stop()
 
    def _stop(self):
        self._running = False
        if self._cap:
            self._cap.release()
        self._cap = None
 
    def _on_close(self):
        self._stop()
        self.destroy()
 
 
if __name__ == "__main__":
    app = App()
    app.mainloop()