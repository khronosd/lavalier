"""The one place that names the pendant's vendor software, so it can be recognised on this Mac.

Used to warn about its launch agent (`doctor`) and to treat its running desktop app as another
device user (`lock`). Never printed as the recorder's own copy: only echoed from what is found.
"""

# Labels of the vendor's launch agents and desktop apps known to sync this pendant.
KNOWN_PENDANT_AGENT_LABELS = ("Limitless",)


def is_vendor_app_command(command: str) -> bool:
    """True for a process running from the vendor's desktop app bundle."""
    return any(f"/Applications/{label}.app/" in command for label in KNOWN_PENDANT_AGENT_LABELS)
