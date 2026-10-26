"""Single source of truth for the app version and the release repository the in-app updater trusts."""
__version__ = "0.5.0"

# GitHub "owner/repo" whose releases the in-app updater checks and installs from.
# Change this if you publish releases from your own fork (the updater installs whatever is published there).
UPDATE_REPO = "ShanudhaTirosh/OpenSMS"
