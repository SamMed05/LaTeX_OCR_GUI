import tkinter as tk
from tkinter import scrolledtext, ttk
from PIL import ImageGrab, Image, ImageTk

import matplotlib
matplotlib.use('TkAgg')
from matplotlib.figure import Figure
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg

from pix2tex.cli import LatexOCR

print("Initializing LatexOCR model...")
try:
    ocr = LatexOCR()
except Exception as e:
    print(f"Error loading model: {e}")
    ocr = None


class MathJaxOCRApp:
    def __init__(self, root):
        self.root = root
        self.root.title("Formula OCR → MathJax")
        self.root.geometry("850x460")
        self.root.configure(bg="#ffffff")
        
        # UI Theme Styling
        self.style = ttk.Style()
        self.style.theme_use('clam')
        self.style.configure(
            'TButton', 
            font=('Helvetica', 10, 'bold'), 
            foreground='#ffffff', 
            background='#3b82f6', 
            borderwidth=0
        )
        self.style.map('TButton', background=[('active', '#2563eb')])
        
        self.tk_img = None 
        self.setup_ui()

    def setup_ui(self):
        # --- Top Action Area ---
        top_frame = tk.Frame(self.root, bg="#ffffff")
        top_frame.pack(pady=10) # Reduced padding
        
        self.btn = ttk.Button(
            top_frame, 
            text="📋 Convert Clipboard Image", 
            command=self.paste_and_convert
        )
        self.btn.pack(side=tk.LEFT, ipadx=12, ipady=4)
        
        # Checkbox for MathJax delimiter toggling
        self.display_mode_var = tk.BooleanVar(value=False) # Disabled/Unchecked by default
        self.chk_box = tk.Checkbutton(
            top_frame, 
            text="Use Block Display ($$ ... $$) instead of Inline (\\( ... \\))",
            variable=self.display_mode_var,
            bg="#ffffff",
            activebackground="#ffffff",
            font=('Helvetica', 9),
            fg="#4b5563"
        )
        self.chk_box.pack(side=tk.LEFT, padx=15)

        # --- Middle Preview Workspace ---
        workspace_frame = tk.Frame(self.root, bg="#ffffff")
        workspace_frame.pack(fill=tk.BOTH, expand=True, padx=15, pady=0)
        
        # Left Panel: Image Snippet Preview
        preview_box = tk.LabelFrame(
            workspace_frame, text=" Clipboard Preview ", 
            bg="#ffffff", fg="#4b5563", font=('Helvetica', 9, 'bold'), bd=1, relief=tk.SOLID
        )
        preview_box.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=5, pady=5)
        
        self.preview_label = tk.Label(preview_box, text="No image grabbed yet", bg="#ffffff", fg="#9ca3af", font=('Helvetica', 9))
        self.preview_label.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

        # Right Panel: Math Structural Renderer
        render_box = tk.LabelFrame(
            workspace_frame, text=" Rendered Equation ", 
            bg="#ffffff", fg="#4b5563", font=('Helvetica', 9, 'bold'), bd=1, relief=tk.SOLID
        )
        render_box.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True, padx=5, pady=5)
        
        # Matplotlib canvas configuration matching the pure white ecosystem
        self.fig = Figure(figsize=(4, 1.5), facecolor='#ffffff')
        self.ax = self.fig.add_subplot(111)
        self.ax.axis('off')
        self.canvas = FigureCanvasTkAgg(self.fig, master=render_box)
        self.canvas.get_tk_widget().pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
        self.canvas.get_tk_widget().configure(bg="#ffffff")

        # --- Bottom Syntax Output Panel ---
        output_box = tk.LabelFrame(
            self.root, text=" LaTeX / MathJax Code Output ", 
            bg="#ffffff", fg="#4b5563", font=('Helvetica', 9, 'bold'), bd=1, relief=tk.SOLID
        )
        output_box.pack(fill=tk.X, padx=20, pady=10)
        
        self.output = scrolledtext.ScrolledText(
            output_box, width=80, height=2, # Cut height down to a clean 2 lines
            font=('Consolas', 10), bg="#f9fafb", fg="#1f2937", 
            bd=0, highlightthickness=1, highlightbackground="#e5e7eb"
        )
        self.output.pack(fill=tk.BOTH, expand=True, padx=8, pady=6)

    def image_from_clipboard(self):
        img = ImageGrab.grabclipboard()
        if isinstance(img, Image.Image):
            return img
        return None

    def paste_and_convert(self):
        try:
            img = self.image_from_clipboard()
            if img is None:
                raise ValueError("No image found in clipboard. Copy a formula screenshot first!")

            # 1. Scaling preview bounding-box down to prevent bloating the interface
            preview_copy = img.copy()
            preview_copy.thumbnail((380, 180))
            self.tk_img = ImageTk.PhotoImage(preview_copy)
            self.preview_label.config(image=self.tk_img, text="")
            
            # 2. Fire up the OCR Model Engine
            if ocr is None:
                raise RuntimeError("OCR model failed to initialize.")
            latex = ocr(img)
            
            # 3. Apply Delimiter Wrap Conditional Logic
            if self.display_mode_var.get():
                mathjax = f"$${latex}$$"
            else:
                mathjax = f"\\({latex}\\)"

            # 4. Write string code structure
            self.output.delete("1.0", tk.END)
            self.output.insert(tk.END, mathjax)

            # 5. Paint the rendered LaTeX string vector to Matplotlib
            self.ax.clear()
            self.ax.axis('off')
            self.ax.text(0.5, 0.5, f"${latex}$", size=16, va='center', ha='center', color='#111827')
            self.canvas.draw()

        except Exception as e:
            self.output.delete("1.0", tk.END)
            self.output.insert(tk.END, f"Error: {e}")
            self.ax.clear()
            self.ax.axis('off')
            self.canvas.draw()


if __name__ == "__main__":
    root = tk.Tk()
    app = MathJaxOCRApp(root)
    root.mainloop()