#!/bin/bash
cat > out.txt << EOM
This heredoc content has < and > characters but not at column 0
<<< and === and >>> never start the line
EOM
