# OyapleDebateMonitor
This is the debate monitor for Oypale.com, have fun (The Docket)

The Docket
Desktop app that tracks live debates on oyaple. 

You need Python 3.10 or newer, an Oyaple account, valid SESSION_ID and XSRF_TOKEN
Make a folder for the script. The app will create a cache file in that folder. Move the script inside the folder

Install packages: pip install requests PyQt6 urllib3
Open OyapleDebateMonitor.py and put your SESSION_ID and XSRF_TOKEN near the top. The app won't run if they're empty. Keep them private.

Run it: python OyapleDebateMonitor.py
The window shows LIVE, LAPSED, and CLOSED on the left. Click a debate to see details on the right.

Settings you can change near the top: THREAD_COUNT, CURRENT_SEASON, BACKGROUND_SCAN_INTERVAL, ACTIVE_DEBATE_PRIORITY_INTERVAL, RECENT_HISTORY_WINDOW. Lower THREAD_COUNT if you get 429 errors.
If no debates show up, check your session values and CURRENT_SEASON. Delete oyaple_users_cache.json to reset the user list. If the window stays empty, give it time to scan.

Close the window to stop.

DISCLAIMER; AI WAS USED IN FORMATTING THE UI
