import tkinter as tk
from tkinter import scrolledtext
from PIL import ImageGrab, Image
import io

from pix2tex.cli import LatexOCR

# Load model once
ocr = LatexOCR()

def image_from_clipboard():
    img = ImageGrab.grabclipboard()
    if isinstance(img, Image.Image):
        return img
    return None

def convert_clipboard():
    try:
        img = image_from_clipboard()
        if img is None:
            raise ValueError("No image found in clipboard.")

        latex = ocr(img)
        mathjax = f"\\({latex}\\)"

        output.delete("1.0", tk.END)
        output.insert(tk.END, mathjax)

        print("OCR success:", latex)

    except Exception as e:
        print("Error:", e)
        output.delete("1.0", tk.END)
        output.insert(tk.END, f"Error: {e}")

def paste_and_convert():
    convert_clipboard()

# GUI
root = tk.Tk()
root.title("OCR → MathJax")

btn = tk.Button(root, text="Convert Clipboard (Ctrl+V image)", command=paste_and_convert)
btn.pack(pady=10)

output = scrolledtext.ScrolledText(root, width=80, height=10)
output.pack()

root.mainloop()
input("Press Enter to exit...")