OVRP Moderation Bot

A Discord moderation bot for OVRP | Oceanview Roleplay featuring:

Modern moderation DMs (ban/mute/warn/kick) using consistent embed styling.
/reqban workflow (moderators request, admins approve/deny).
Full Ban Appeal System with staff review panel, “request more info” loop, and modlog history viewing.

Requirements --
Python 3.11+ (recommended 3.12)
discord.py 2.3+
SQLite (built-in)

Setup --
Install deps:
pip install -U discord.py
Configure IDs inside the bot file (guild, roles, channels).
Run:
python MM.py

Configuration --
SIMULATION_MODE = True
Used for testing: allows appeal flow to run end-to-end even if the user isn’t actually banned and removes timer enforcement.
SIMULATION_MODE = False
Full enforcement: eligibility checks, ban state checks, cooldowns, timers.

Appeal Eligibility (summary) --
Appeal button appears only for:
Permanent bans, OR
Temporary bans > 4 days
Must wait 72h after ban before appealing (disabled in SIMULATION_MODE)
