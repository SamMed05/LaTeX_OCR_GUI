import tkinter as tk
from tkinter import scrolledtext, ttk
from PIL import ImageGrab, Image, ImageTk

# Force Matplotlib to use the Tkinter backend before importing Figure
import matplotlib
matplotlib.use('TkAgg')
from matplotlib.figure import Figure
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg

# Import the core OCR engine
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
        self.root.geometry("850x500")
        self.root.configure(bg="#ffffff")
        
        # Configure a modern, clean style for ttk widgets
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
        
        # Persistent state attributes
        self.tk_img = None        # Keeps a reference to the PIL image to prevent garbage collection
        self.current_latex = ""   # Stores the raw LaTeX string output from the OCR model
        self.setup_ui()

        # Bind Ctrl+V (both lowercase and uppercase states) globally to the root window
        self.root.bind("<Control-v>", self.paste_and_convert)
        self.root.bind("<Control-V>", self.paste_and_convert)

    def setup_ui(self):
        # --- TOP CONTROL BAR ---
        top_frame = tk.Frame(self.root, bg="#ffffff")
        top_frame.pack(pady=10)
        
        # Action button to trigger conversion manually
        self.btn = ttk.Button(
            top_frame, 
            text="Convert Clipboard Image", 
            command=self.paste_and_convert
        )
        self.btn.pack(side=tk.LEFT, ipadx=15, ipady=5)
        
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
        self.chk_inline.pack(side=tk.LEFT, padx=(20, 10))

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
        self.chk_block.pack(side=tk.LEFT, padx=10)

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
            self.root, text=" LaTeX / MathJax Code Output ", 
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
            text="Find & Replace",
            width=3,
            command=self.open_search_replace_dialog
        )
        self.search_btn.pack(side=tk.LEFT, padx=(0, 5))

        # The copy button to append contents to system clipboard
        self.copy_btn = ttk.Button(
            action_bar,
            text="Copy to Clipboard",
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
            self.copy_btn.config(text="Copied!")
            self.root.after(1500, lambda: self.copy_btn.config(text="Copy to Clipboard"))

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

    # UPDATED: Added an optional event argument to support Tkinter's event-binding architecture
    def paste_and_convert(self, event=None):
        """Main execution flow: Extracts image, triggers OCR, updates rendering & text outputs."""
        try:
            img = self.image_from_clipboard()
            if img is None:
                # Intelligent intercept: If triggered by Ctrl+V keyboard shortcut, but clipboard has text data, 
                # do not raise an error window. Pass execution back so text fields paste natively.
                if event is not None:
                    return
                raise ValueError("No image found in clipboard. Copy a formula screenshot first!")

            # Process image thumbnail resizing for preview UI
            preview_copy = img.copy()
            preview_copy.thumbnail((380, 180))
            self.tk_img = ImageTk.PhotoImage(preview_copy)
            self.preview_label.config(image=self.tk_img, text="")
            
            if ocr is None:
                raise RuntimeError("OCR model failed to initialize.")
            
            # Pass image to the transformer model to predict LaTeX string
            self.current_latex = ocr(img)
            self.update_output_display()

            # Clear former plots and use Matplotlib math engine to render LaTeX live
            self.ax.clear()
            self.ax.axis('off')
            self.ax.text(0.5, 0.5, f"${self.current_latex}$", size=16, va='center', ha='center', color='#111827')
            self.canvas.draw()

            # Return 'break' to intercept text-paste handling if an image was processed successfully via key shortcut
            return "break"

        except Exception as e:
            # Handle empty clipboard data or missing dependencies gracefully inside UI
            self.output.delete("1.0", tk.END)
            self.output.insert(tk.END, f"Error: {e}")
            self.ax.clear()
            self.ax.axis('off')
            self.canvas.draw()


if __name__ == "__main__":
    root = tk.Tk()
    app = MathJaxOCRApp(root)
    root.mainloop()