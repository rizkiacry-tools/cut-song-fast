cut query start end:
    python3 cut.py "{{query}}" "{{start}}" "{{end}}"

search query:
    termux-open-url $$(python3 cut.py search "{{query}}")
