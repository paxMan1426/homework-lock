import sys
from pathlib import Path

import customtkinter as ctk
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


@pytest.fixture(scope="session")
def tk_root():
    r = ctk.CTk()
    r.geometry("1x1+0+0")
    yield r
    r.destroy()


@pytest.fixture
def root(tk_root):
    yield tk_root
    for child in list(tk_root.winfo_children()):
        child.destroy()
