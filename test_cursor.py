#!/usr/bin/env python3
"""
Test the QTextCursor fix
"""

import sys

def test_qtextcursor():
    """Test QTextCursor usage"""
    try:
        from PySide6.QtWidgets import QApplication, QTextEdit
        from PySide6.QtGui import QTextCursor
        
        app = QApplication(sys.argv)
        
        text_edit = QTextEdit()
        text_edit.append("Test message")
        
        cursor = text_edit.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        text_edit.setTextCursor(cursor)
        
        print("✅ QTextCursor.MoveOperation.End works correctly!")
        return True
        
    except Exception as e:
        print(f"❌ QTextCursor test failed: {e}")
        return False

if __name__ == "__main__":
    test_qtextcursor()