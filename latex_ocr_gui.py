import os
# Must be set before albumentations gets imported (pix2tex pulls it in transitively)
os.environ.setdefault("NO_ALBUMENTATIONS_UPDATE", "1")

import warnings
# Both of these are harmless library chatter, not application errors.
warnings.filterwarnings("ignore", category=UserWarning, module=r"pydantic.*")
warnings.filterwarnings("ignore", category=UserWarning, module=r"albumentations.*")

import threading
import queue

import tkinter as tk
from tkinter import scrolledtext, ttk
from PIL import ImageGrab, Image, ImageTk, ImageDraw

# Force Matplotlib to use the Tkinter backend before importing Figure
import matplotlib
matplotlib.use('TkAgg')
matplotlib.rcParams['mathtext.fontset'] = 'cm'
from matplotlib.figure import Figure
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg

# NOTE: pix2tex (and the torch/albumentations stack behind it) is intentionally
# NOT imported here at module level. Importing it is the slow part of startup,
# so it's deferred to a background thread in LaTeXOCRApp._load_model_worker.
# This lets the window appear immediately instead of blocking on the import.


# ---------------------------------------------------------------------------
# Icon helpers
# ---------------------------------------------------------------------------
# Emoji glyphs are drawn by the OS's color-emoji font, which has totally
# different metrics (baseline, advance width, vertical centering) than the
# button's regular text font. That mismatch is exactly why emoji inside a
# Tkinter/ttk button end up looking shifted down and undersized on Windows.
# Drawing simple icons with PIL and using them as a normal PhotoImage avoids
# the problem entirely, since it's just a bitmap with no font metrics at all.

def _render_icon(draw_fn, size=18, supersample=4, color="#ffffff"):
    """Draw an icon at a higher resolution and downscale for crisp edges."""
    big = size * supersample
    img = Image.new("RGBA", (big, big), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    draw_fn(d, big, color)
    img = img.resize((size, size), Image.LANCZOS)
    return ImageTk.PhotoImage(img)


def _draw_paste_icon(d, s, color):
    w = max(1, int(s * 0.045))
    d.rounded_rectangle([s * 0.18, s * 0.16, s * 0.82, s * 0.92], radius=s * 0.05, outline=color, width=w)
    d.rounded_rectangle([s * 0.36, s * 0.04, s * 0.64, s * 0.20], radius=s * 0.03, outline=color, width=w)
    for y in (0.40, 0.56, 0.72):
        d.line([s * 0.30, s * y, s * 0.70, s * y], fill=color, width=w)


def _draw_copy_icon(d, s, color):
    w = max(1, int(s * 0.05))
    d.rounded_rectangle([s * 0.34, s * 0.10, s * 0.92, s * 0.68], radius=s * 0.05, outline=color, width=w)
    d.rounded_rectangle([s * 0.08, s * 0.32, s * 0.66, s * 0.90], radius=s * 0.05, outline=color, width=w)


def _draw_search_icon(d, s, color):
    w = max(1, int(s * 0.06))
    d.ellipse([s * 0.12, s * 0.12, s * 0.62, s * 0.62], outline=color, width=w)
    d.line([s * 0.58, s * 0.58, s * 0.90, s * 0.90], fill=color, width=w + 1)


class Spinner(tk.Canvas):
    """Small animated arc spinner used while OCR inference is running."""

    def __init__(self, master, size=22, color="#3b82f6", **kwargs):
        kwargs.setdefault("highlightthickness", 0)
        super().__init__(master, width=size, height=size, **kwargs)
        self.size = size
        self.color = color
        self._angle = 0
        self._running = False
        self._job = None

    def start(self):
        if self._running:
            return
        self._running = True
        self._tick()

    def stop(self):
        self._running = False
        if self._job is not None:
            self.after_cancel(self._job)
            self._job = None
        self.delete("all")

    def _tick(self):
        if not self._running:
            return
        self.delete("all")
        pad = max(2, int(self.size * 0.12))
        self.create_arc(
            pad, pad, self.size - pad, self.size - pad,
            start=self._angle, extent=130, style=tk.ARC,
            width=3, outline=self.color
        )
        self._angle = (self._angle - 24) % 360
        self._job = self.after(45, self._tick)


class LaTeXOCRApp:
    def __init__(self, root):
        self.root = root
        self.root.title("Formula OCR → LaTeX")
        self.root.geometry("850x520")
        self.root.configure(bg="#ffffff")

        # Configure a modern, clean style for ttk widgets
        self.style = ttk.Style()
        self.style.theme_use('clam')
        self.style.configure(
            'TButton',
            font=('Helvetica', 10, 'bold'),
            foreground='#ffffff',
            background='#3b82f6',
            borderwidth=0,
            padding=(10, 6)
        )
        self.style.map(
            'TButton',
            background=[('active', '#2563eb'), ('disabled', '#93c5fd')],
        )
        self.style.configure(
            'Thin.Horizontal.TProgressbar',
            troughcolor='#e5e7eb',
            background='#3b82f6',
            thickness=4,
            borderwidth=0,
        )

        # Persistent state attributes
        self.tk_img = None        # Keeps a reference to the PIL image to prevent garbage collection
        self.current_latex = ""   # Stores the raw LaTeX string output from the OCR model
        self.ocr = None           # The LatexOCR model, populated once background loading finishes
        self.model_ready = False
        self.ocr_busy = False
        self.pending_image = None  # Image grabbed before the model finished loading
        self._task_queue = queue.Queue()  # Cross-thread handoff; only the main thread touches Tk widgets

        # Icons kept as attributes so PhotoImage objects aren't garbage collected
        self.icon_paste = _render_icon(_draw_paste_icon)
        self.icon_copy = _render_icon(_draw_copy_icon)
        self.icon_search = _render_icon(_draw_search_icon)

        self.setup_ui()

        # Bind Ctrl+V (both lowercase and uppercase states) globally to the root window
        self.root.bind("<Control-v>", self.paste_and_convert)
        self.root.bind("<Control-V>", self.paste_and_convert)

        # Kick off model loading in the background so the window is usable immediately
        threading.Thread(target=self._load_model_worker, daemon=True).start()
        self.root.after(80, self._poll_tasks)

    def setup_ui(self):
        # Thin indeterminate progress bar, visible only while the model loads
        self.loading_bar = ttk.Progressbar(
            self.root, mode='indeterminate', style='Thin.Horizontal.TProgressbar'
        )
        self.loading_bar.pack(fill=tk.X, side=tk.TOP)
        self.loading_bar.start(8)

        # --- TOP CONTROL BAR ---
        top_frame = tk.Frame(self.root, bg="#ffffff")
        top_frame.pack(pady=10, fill=tk.X)

        btn_row = tk.Frame(top_frame, bg="#ffffff")
        btn_row.pack(anchor=tk.W, padx=15)

        # Action button to trigger conversion manually (disabled until the model is ready)
        self.btn = ttk.Button(
            btn_row,
            text="  Loading model…",
            image=self.icon_paste,
            compound=tk.LEFT,
            state=tk.DISABLED,
            command=self.paste_and_convert
        )
        self.btn.pack(side=tk.LEFT)

        # Spinner shown only while OCR inference is running on an image
        self.spinner = Spinner(btn_row, size=22, color="#3b82f6", bg="#ffffff")
        self.spinner.pack(side=tk.LEFT, padx=(10, 0))

        # Checkbox variables to track wrapper states
        self.inline_var = tk.BooleanVar(value=False)
        self.block_var = tk.BooleanVar(value=False)

        # Inline toggle setup
        self.chk_inline = tk.Checkbutton(
            top_frame,
            text="Inline Wrapper (\\( ... \\))",
            variable=self.inline_var,
            bg="#ffffff",
            activebackground="#ffffff",
            font=('Helvetica', 9),
            fg="#4b5563",
            command=self.handle_inline_toggle
        )
        self.chk_inline.pack(anchor=tk.W, padx=(15, 0), pady=(8, 0))

        # Block display toggle setup
        self.chk_block = tk.Checkbutton(
            top_frame,
            text="Block Display Wrapper ($$ ... $$)",
            variable=self.block_var,
            bg="#ffffff",
            activebackground="#ffffff",
            font=('Helvetica', 9),
            fg="#4b5563",
            command=self.handle_block_toggle
        )
        self.chk_block.pack(anchor=tk.W, padx=(15, 0))

        # Status line: reflects model-loading / OCR-running / ready states
        self.status_label = tk.Label(
            top_frame, text="Initializing model…",
            bg="#ffffff", fg="#9ca3af", font=('Helvetica', 8, 'italic')
        )
        self.status_label.pack(anchor=tk.W, padx=(15, 0), pady=(6, 0))

        # --- MID-SECTION WORKSPACE (PREVIEW & RENDER) ---
        workspace_frame = tk.Frame(self.root, bg="#ffffff")
        workspace_frame.pack(fill=tk.BOTH, expand=True, padx=15, pady=0)

        # Left Panel: Source Image Preview
        preview_box = tk.LabelFrame(
            workspace_frame, text=" Clipboard Preview ",
            bg="#ffffff", fg="#4b5563", font=('Helvetica', 9, 'bold'), bd=1, relief=tk.SOLID
        )
        preview_box.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=5, pady=5)

        self.preview_label = tk.Label(preview_box, text="No image grabbed yet", bg="#ffffff", fg="#9ca3af", font=('Helvetica', 9))
        self.preview_label.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

        # Right Panel: Live Matplotlib LaTeX Render
        render_box = tk.LabelFrame(
            workspace_frame, text=" Rendered Equation ",
            bg="#ffffff", fg="#4b5563", font=('Helvetica', 9, 'bold'), bd=1, relief=tk.SOLID
        )
        render_box.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True, padx=5, pady=5)

        # Embed Matplotlib Figure into Tkinter Canvas
        self.fig = Figure(figsize=(4, 1.5), facecolor='#ffffff')
        self.ax = self.fig.add_subplot(111)
        self.ax.axis('off')  # Turn off axis lines and labels for mathematical rendering
        self.canvas = FigureCanvasTkAgg(self.fig, master=render_box)
        self.canvas.get_tk_widget().pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
        self.canvas.get_tk_widget().configure(bg="#ffffff")

        # --- BOTTOM SECTION: TEXT OUTPUT & UTILITY BUTTONS ---
        output_box = tk.LabelFrame(
            self.root, text=" LaTeX Code Output ",
            bg="#ffffff", fg="#4b5563", font=('Helvetica', 9, 'bold'), bd=1, relief=tk.SOLID
        )
        output_box.pack(fill=tk.X, padx=20, pady=10)

        # ScrolledText provides a scrollable multi-line textbox
        self.output = scrolledtext.ScrolledText(
            output_box, width=80, height=5,
            font=('Consolas', 10), bg="#f9fafb", fg="#1f2937",
            bd=0, highlightthickness=1, highlightbackground="#e5e7eb"
        )
        self.output.pack(fill=tk.BOTH, expand=True, padx=8, pady=(6, 2))

        # Control container frame to place utilities side-by-side at the bottom right
        action_bar = tk.Frame(output_box, bg="#ffffff")
        action_bar.pack(anchor=tk.E, padx=8, pady=(2, 6))

        # Search & Replace Button
        self.search_btn = ttk.Button(
            action_bar,
            text="  Find & Replace",
            image=self.icon_search,
            compound=tk.LEFT,
            command=self.open_search_replace_dialog
        )
        self.search_btn.pack(side=tk.LEFT, padx=(0, 5))

        # The copy button to append contents to system clipboard
        self.copy_btn = ttk.Button(
            action_bar,
            text="  Copy to Clipboard",
            image=self.icon_copy,
            compound=tk.LEFT,
            command=self.copy_to_clipboard
        )
        self.copy_btn.pack(side=tk.LEFT)

    def handle_inline_toggle(self):
        """Enforces mutual exclusion. If Inline is selected, uncheck Block Display."""
        if self.inline_var.get():
            self.block_var.set(False)
        self.update_output_display()

    def handle_block_toggle(self):
        """Enforces mutual exclusion. If Block Display is selected, uncheck Inline."""
        if self.block_var.get():
            self.inline_var.set(False)
        self.update_output_display()

    def update_output_display(self):
        """Formats the raw string according to the active checkbox wrapper and pushes it to UI."""
        if not self.current_latex:
            return

        if self.inline_var.get():
            formatted_text = f"\\({self.current_latex}\\)"
        elif self.block_var.get():
            formatted_text = f"$${self.current_latex}$$"
        else:
            formatted_text = self.current_latex

        # Clear text from start ("1.0") to end, then insert new formatted string
        self.output.delete("1.0", tk.END)
        self.output.insert(tk.END, formatted_text)

    def image_from_clipboard(self):
        """Fetches system clipboard data and verifies if it is a valid PIL Image."""
        img = ImageGrab.grabclipboard()
        if isinstance(img, Image.Image):
            return img
        return None

    def copy_to_clipboard(self):
        """Copies current text box contents to system clipboard with visual feedback."""
        text_to_copy = self.output.get("1.0", tk.END).strip()

        if text_to_copy and not text_to_copy.startswith("Error:"):
            self.root.clipboard_clear()
            self.root.clipboard_append(text_to_copy)

            # Change button state temporarily to give the user confirmation
            self.copy_btn.config(text="  Copied!")
            self.root.after(1500, lambda: self.copy_btn.config(text="  Copy to Clipboard"))

    # Search and Replace modal dialog logic
    def open_search_replace_dialog(self):
        """Spawns a clean helper window to find and replace substrings inside the output box."""
        dialog = tk.Toplevel(self.root)
        dialog.title("Find & Replace")
        dialog.geometry("320x140")
        dialog.resizable(False, False)
        dialog.configure(bg="#ffffff")

        # Focus handling: forces focus to popup and keeps it on top of main window
        dialog.transient(self.root)
        dialog.grab_set()

        # Find Entry Input
        tk.Label(dialog, text="Find:", bg="#ffffff", fg="#4b5563", font=('Helvetica', 9)).grid(row=0, column=0, padx=10, pady=10, sticky="e")
        find_entry = tk.Entry(dialog, width=22, font=('Consolas', 10), highlightthickness=1, highlightbackground="#e5e7eb")
        find_entry.grid(row=0, column=1, padx=10, pady=10)
        find_entry.focus_set()

        # Replace Entry Input
        tk.Label(dialog, text="Replace with:", bg="#ffffff", fg="#4b5563", font=('Helvetica', 9)).grid(row=1, column=0, padx=10, pady=5, sticky="e")
        replace_entry = tk.Entry(dialog, width=22, font=('Consolas', 10), highlightthickness=1, highlightbackground="#e5e7eb")
        replace_entry.grid(row=1, column=1, padx=10, pady=5)

        def execute_replace():
            find_str = find_entry.get()
            replace_str = replace_entry.get()
            if find_str:
                # Read current content from the textbox, swap values, and reinsert
                content = self.output.get("1.0", tk.END)
                updated_content = content.replace(find_str, replace_str)

                self.output.delete("1.0", tk.END)
                self.output.insert(tk.END, updated_content.strip())

                # Sync back adjustments into the background storage variable
                self.current_latex = self.output.get("1.0", tk.END).strip()
                # Strip out wrappers if they are checked to preserve pure variable value
                if self.inline_var.get():
                    self.current_latex = self.current_latex.removeprefix("\\(").removesuffix("\\)")
                elif self.block_var.get():
                    self.current_latex = self.current_latex.removeprefix("$$").removesuffix("$$")

                dialog.destroy()

        # Action execution button inside dialog
        action_btn = ttk.Button(dialog, text="Replace All", command=execute_replace)
        action_btn.grid(row=2, column=0, columnspan=2, pady=12)

    # ------------------------------------------------------------------
    # Background model loading
    # ------------------------------------------------------------------
    def _load_model_worker(self):
        """Runs off the main thread: heavy import + model construction."""
        try:
            from pix2tex.cli import LatexOCR  # deferred: this import is the slow part
            model = LatexOCR()
            self._task_queue.put(("model_loaded", model))
        except Exception as e:
            self._task_queue.put(("model_error", str(e)))

    def _poll_tasks(self):
        """Runs on the main thread via root.after; the only place Tk widgets get touched
        in response to background-thread work."""
        try:
            while True:
                kind, payload = self._task_queue.get_nowait()
                if kind == "model_loaded":
                    self._on_model_loaded(payload)
                elif kind == "model_error":
                    self._on_model_error(payload)
                elif kind == "ocr_done":
                    self._on_ocr_done(payload)
                elif kind == "ocr_error":
                    self._on_ocr_error(payload)
        except queue.Empty:
            pass
        self.root.after(80, self._poll_tasks)

    def _on_model_loaded(self, model):
        self.ocr = model
        self.model_ready = True
        self.loading_bar.stop()
        self.loading_bar.pack_forget()
        self.btn.config(state=tk.NORMAL, text="  Convert Clipboard Image")
        self.status_label.config(text="Model ready — paste an image with Ctrl+V", fg="#9ca3af")

        # If the user pasted something while the model was still loading, convert it now
        if self.pending_image is not None:
            img, self.pending_image = self.pending_image, None
            self._run_ocr(img)

    def _on_model_error(self, message):
        self.loading_bar.stop()
        self.loading_bar.pack_forget()
        self.status_label.config(text=f"Model failed to load: {message}", fg="#dc2626")
        self.btn.config(state=tk.DISABLED, text="  Model unavailable")

    # ------------------------------------------------------------------
    # Background OCR inference
    # ------------------------------------------------------------------
    def _run_ocr(self, img):
        self.ocr_busy = True
        self.btn.config(state=tk.DISABLED)
        self.status_label.config(text="Running OCR…", fg="#9ca3af")
        self.spinner.start()
        threading.Thread(target=self._ocr_worker, args=(img,), daemon=True).start()

    def _ocr_worker(self, img):
        try:
            latex = self.ocr(img)
            self._task_queue.put(("ocr_done", latex))
        except Exception as e:
            self._task_queue.put(("ocr_error", str(e)))

    def _on_ocr_done(self, latex):
        self.spinner.stop()
        self.ocr_busy = False
        self.btn.config(state=tk.NORMAL)
        self.status_label.config(text="Done", fg="#9ca3af")
        self.current_latex = latex
        self.update_output_display()

        self.ax.clear()
        self.ax.axis('off')
        
        # 1. Sanitize common items ONLY for the preview canvas string
        # (This keeps your pristine current_latex untouched for code output/clipboard)
        preview_latex = self.current_latex.replace(r"\operatorname*{", r"\operatorname{")
        
        # 2. Safety wrapper to shield Tkinter from Matplotlib parsing errors
        try:
            self.ax.text(0.5, 0.5, f"${preview_latex}$", size=16, va='center', ha='center', color='#111827')
            self.canvas.draw()
        except Exception:
            # Fallback if Matplotlib choked on arrays, matrices, or environments
            self.ax.clear()
            self.ax.axis('off')
            self.ax.text(
                0.5, 0.5, 
                "Preview unavailable\n(Matplotlib cannot render this structure,\nbut the LaTeX code below may still be valid)", 
                size=10, va='center', ha='center', color='#dc2626', weight='bold', style='italic'
            )
            self.canvas.draw()

    def _on_ocr_error(self, message):
        self.spinner.stop()
        self.ocr_busy = False
        self.btn.config(state=tk.NORMAL)
        self.status_label.config(text="OCR failed", fg="#dc2626")
        self.output.delete("1.0", tk.END)
        self.output.insert(tk.END, f"Error: {message}")
        self.ax.clear()
        self.ax.axis('off')
        self.canvas.draw()

    # ------------------------------------------------------------------
    # Entry point shared by the button and Ctrl+V
    # ------------------------------------------------------------------
    def paste_and_convert(self, event=None):
        """Grabs whatever image is on the clipboard and previews it immediately.
        OCR itself only starts once the model has finished loading; if it
        hasn't, the image is held and converted automatically as soon as it is."""
        img = self.image_from_clipboard()
        if img is None:
            # If triggered by Ctrl+V but the clipboard holds text, don't show an
            # error — let the keypress fall through to normal text paste behavior.
            if event is not None:
                return
            self.output.delete("1.0", tk.END)
            self.output.insert(tk.END, "Error: No image found in clipboard. Copy a formula screenshot first!")
            return

        if self.ocr_busy:
            # Avoid overlapping OCR calls; the model isn't built for concurrent inference.
            return "break"

        # Show the preview right away, regardless of whether the model is ready yet
        preview_copy = img.copy()
        preview_copy.thumbnail((380, 180))
        self.tk_img = ImageTk.PhotoImage(preview_copy)
        self.preview_label.config(image=self.tk_img, text="")

        if not self.model_ready:
            self.pending_image = img
            self.status_label.config(
                text="Image captured — will convert automatically once the model finishes loading…",
                fg="#9ca3af"
            )
            return "break"

        self._run_ocr(img)
        return "break"


if __name__ == "__main__":
    root = tk.Tk()
    app = LaTeXOCRApp(root)
    root.mainloop()