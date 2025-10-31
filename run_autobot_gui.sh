#!/bin/bash
# AutoBot GUI Startup Script

echo "🚀 AutoBot GUI Startup"
echo "====================="

# Activate virtual environment if it exists
if [ -d "venv" ]; then
    echo "📦 Activating virtual environment..."
    source venv/bin/activate
fi

# Check if PySide6 is available
python3 -c "import PySide6" 2>/dev/null
if [ $? -ne 0 ]; then
    echo "❌ PySide6 not found. Installing..."
    pip install PySide6
fi

echo "🎯 Starting AutoBot GUI..."
echo "Close this terminal window or press Ctrl+C to stop the application"
echo ""

# Launch the GUI
python3 launch_gui.py